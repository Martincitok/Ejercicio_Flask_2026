from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_mysqldb import MySQL
import os, logging, ssl, socket
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet
import certifi
import asyncio
from aiomqtt import Client, MqttError
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

app = Flask(__name__)
app.config['APPLICATION_ROOT'] = '/tareaflask2'
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

ssl_context = ssl.create_default_context(cafile=certifi.where())
ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED

async def publish_mqtt(topic: str, payload: str, broker_id: int):
    try:
        # Obtener credenciales del broker específico
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT dominio, usuario_broker, pass_encrypted, puerto_tls FROM brokers WHERE id = %s",
            (broker_id,)
        )
        broker = cur.fetchone()
        cur.close()

        if not broker:
            logging.error(f"Broker {broker_id} no encontrado")
            return False

        dominio, usuario, pass_enc, puerto = broker
        try:
            password = decrypt_password(pass_enc)
        except Exception as e:
            logging.error(f"Error al desencriptar contraseña del broker: {str(e)}")
            return False

        # Verificación DNS y conectividad
        try:
            ip = socket.gethostbyname(dominio)
            logging.info(f"Resolución DNS: {dominio} → {ip}")
            
            # Verificar si el puerto está abierto
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)  # 5 segundos de timeout
            result = sock.connect_ex((ip, puerto))
            sock.close()
            
            if result != 0:
                logging.error(f"Puerto {puerto} cerrado o inaccesible en {dominio} ({ip})")
                return False
                
            logging.info(f"Puerto {puerto} accesible en {dominio} ({ip})")
            
        except socket.gaierror as e:
            logging.error(f"Error DNS: {dominio} no se resuelve - {str(e)}")
            return False
        except socket.error as e:
            logging.error(f"Error de conexión: {str(e)}")
            return False

        # Conexión y publicación
        try:
            async with Client(
                dominio,
                port=puerto,
                username=usuario,
                password=password,
                tls_context=ssl_context,
                timeout=10  # 10 segundos de timeout para la conexión MQTT
            ) as client:
                logging.info(f"Conectado a {dominio}:{puerto} con TLS certificado")
                logging.info(f"Publicando en {topic}: {payload}")
                await client.publish(topic, payload, qos=1)
                logging.info("Publicación exitosa")
                return True
        except MqttError as e:
            logging.error(f"Error MQTT: {e}")
            logging.error(f"Configuración MQTT - Broker: {dominio}, Puerto: {puerto}, Usuario: {usuario}")
            return False
        except Exception as e:
            logging.error(f"Error inesperado en MQTT: {str(e)}")
            return False
            
    except Exception as e:
        logging.error(f"Error general en publish_mqtt: {str(e)}")
        return False

@app.before_request
def before_request():
    if request.script_root != app.config['APPLICATION_ROOT']:
        request.environ['SCRIPT_NAME'] = app.config['APPLICATION_ROOT']


app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["MYSQL_USER"]     = os.environ["MYSQL_USER"]
app.config["MYSQL_PASSWORD"] = os.environ["MYSQL_PASSWORD"]
app.config["MYSQL_DB"]       = os.environ["MYSQL_DB"]
app.config["MYSQL_HOST"]     = os.environ["MYSQL_HOST"]
app.config["PERMANENT_SESSION_LIFETIME"] = 300

logging.basicConfig(format='%(asctime)s - CRUD - %(levelname)s - %(message)s', level=logging.INFO)

mysql = MySQL(app)

# Verificar conexión a la base de datos
try:
    with app.app_context():
        cur = mysql.connection.cursor()
        cur.execute("SELECT 1")
        cur.close()
        logging.info(f"Conexión a la base de datos establecida correctamente en {app.config['MYSQL_HOST']}")
except Exception as e:
    logging.error(f"Error al conectar con la base de datos: {str(e)}")
    raise


FERNET_KEY = os.getenv("FERNET_KEY")
fernet = Fernet(FERNET_KEY.encode())

def encrypt_password(raw_password: str) -> str:
    token = fernet.encrypt(raw_password.encode())
    return token.decode()

def decrypt_password(encrypted_password: str) -> str:
    plain = fernet.decrypt(encrypted_password.encode())
    return plain.decode()

def require_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    if request.method == "POST":
        try:
            usuario = request.form.get("usuario")
            password = request.form.get("password")


            cur = mysql.connection.cursor()
            cur.execute("SELECT 1 FROM usuarios WHERE usuario = %s", (usuario,))
            if cur.fetchone():
                flash("El usuario ya existe", "danger")
                cur.close()
                return redirect(url_for('registrar'))

            passhash = generate_password_hash(password, method='scrypt', salt_length=16)
            cur.execute("INSERT INTO usuarios (usuario, hash) VALUES (%s, %s)", (usuario, passhash[17:]))
            mysql.connection.commit()
            cur.close()

            flash("¡Usuario creado con éxito! Por favor inicie sesión", "success")
            logging.info("Se agregó un usuario")
            return redirect(url_for('login'))

        except Exception as e:
            logging.error(f"Error en el registro: {str(e)}")
            flash('Error al registrar el usuario. Por favor, intente nuevamente.', "danger")
            return redirect(url_for('registrar'))

    return render_template('registrar.html')


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            usuario = request.form.get("usuario")
            password = request.form.get("password")

            logging.info(f"Intento de login para usuario: {usuario}")

            cur = mysql.connection.cursor()
            cur.execute("SELECT id, hash, tema FROM usuarios WHERE usuario = %s", (usuario,))
            fila = cur.fetchone()
            if fila and check_password_hash('scrypt:32768:8:1$' + fila[1], password):
                session.permanent = True
                session["user_id"]  = fila[0]
                session["username"] = usuario
                session["tema"]     = fila[2]
                logging.info(f"Usuario autenticado exitosamente: {usuario}")
                cur.close()
                return redirect(url_for('index'))
            else:
                flash('Usuario o contraseña incorrecto', "danger")
                logging.warning(f"Intento de login fallido para usuario: {usuario}")
                cur.close()
                return redirect(url_for('login'))

        except Exception as e:
            logging.error(f"Error en el login: {str(e)}")
            flash('Error al iniciar sesión. Por favor, intente nuevamente.', "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
@require_login
def index():
    try:
        user_id = session["user_id"]
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT n.id, n.nombre, n.id_dispositivo, b.dominio
            FROM nodos AS n
            JOIN brokers AS b ON n.broker_id = b.id
            WHERE n.usuario_id = %s
        """, (user_id,))
        nodos = cur.fetchall()

        cur.execute("SELECT tema FROM usuarios WHERE id = %s", (user_id,))
        tema_result = cur.fetchone()
        tema_preferido = tema_result[0] if tema_result else 0

        dispositivo_seleccionado = session.get("id_dispositivo")

        cur.close()
        return render_template(
            'bienvenida.html',
            username=session.get("username"),
            nodos=nodos,
            tema_preferido=tema_preferido,
            dispositivo_seleccionado=dispositivo_seleccionado
        )
    except Exception as e:
        logging.error(f"Error al obtener nodos: {str(e)}")
        flash("Error al cargar la lista de nodos", "danger")
        return redirect(url_for('index'))


@app.route('/seleccionar_dispositivo', methods=['POST'])
@require_login
def seleccionar_dispositivo():
    try:
        id_dispositivo = request.form.get('id_dispositivo')
        if id_dispositivo:
            session['id_dispositivo'] = id_dispositivo
            flash("Dispositivo seleccionado correctamente", "success")
        else:
            session.pop('id_dispositivo', None)
            flash("Por favor, seleccione un dispositivo para ver sus opciones de control.", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"Error al seleccionar dispositivo: {str(e)}")
        flash("Error al seleccionar el dispositivo", "danger")
        return redirect(url_for('index'))


@app.route('/flash', methods=['POST'])
@require_login
def flash_command():
    try:
        id_dispositivo = session.get("id_dispositivo")
        if not id_dispositivo:
            flash("No hay dispositivo seleccionado", "danger")
            return redirect(url_for('index'))

        # Obtener el broker_id del dispositivo seleccionado
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT b.id FROM nodos n JOIN brokers b ON n.broker_id = b.id WHERE n.id_dispositivo = %s AND n.usuario_id = %s",
            (id_dispositivo, session["user_id"])
        )
        broker_result = cur.fetchone()
        cur.close()

        if not broker_result:
            flash("No se encontró el broker asociado al dispositivo", "danger")
            return redirect(url_for('index'))

        broker_id = broker_result[0]
        topic = f"{id_dispositivo}/destello"
        payload = "1"

        success = asyncio.run(publish_mqtt(topic, payload, broker_id))

        if success:
            flash("Comando de destello enviado correctamente", "success")
        else:
            flash("Error al enviar el comando de destello. Verifique la conexión MQTT.", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"Error al procesar comando de destello: {str(e)}")
        flash('Error al enviar el comando de destello', "danger")
        return redirect(url_for('index'))


@app.route('/setpoint', methods=['GET', 'POST'])
@require_login
def setpoint_command():
    try:
        id_dispositivo = session.get("id_dispositivo")
        if not id_dispositivo:
            flash("No hay dispositivo seleccionado", "danger")
            return redirect(url_for('index'))

        # Obtener el broker_id del dispositivo seleccionado
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT b.id FROM nodos n JOIN brokers b ON n.broker_id = b.id WHERE n.id_dispositivo = %s AND n.usuario_id = %s",
            (id_dispositivo, session["user_id"])
        )
        broker_result = cur.fetchone()
        cur.close()

        if not broker_result:
            flash("No se encontró el broker asociado al dispositivo", "danger")
            return redirect(url_for('index'))

        broker_id = broker_result[0]
        topic = f"{id_dispositivo}/setpoint"

        if request.method == 'GET':
            setpoint = request.args.get('setpoint')
            if not setpoint or setpoint.strip() == '':
                logging.info("Intento de actualizar setpoint sin valor")
                flash("No se proporcionó un valor de setpoint", "danger")
                return redirect(url_for('index'))

            success = asyncio.run(publish_mqtt(topic, setpoint, broker_id))

            if success:
                flash(f"Setpoint actualizado correctamente a {setpoint}", "success")
            else:
                flash("Error al actualizar el setpoint. Verifique la conexión MQTT.", "danger")
            return redirect(url_for('index'))

        logging.info("Recibida petición POST a /setpoint")
        flash("Setpoint actualizado correctamente", "success")
        return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Error al procesar setpoint: {str(e)}")
        flash('Error al actualizar el setpoint', "danger")
        return redirect(url_for('index'))


@app.route('/agregar_nodo', methods=['GET', 'POST'])
@require_login
def agregar_nodo():
    user_id = session["user_id"]
    if request.method == 'POST':
        try:
            nombre         = request.form.get('nombre')
            id_dispositivo = request.form.get('id_dispositivo')
            broker_id      = request.form.get('broker_id')

            if not nombre or not id_dispositivo or not broker_id:
                flash("Todos los campos son obligatorios", "danger")
                return redirect(url_for('agregar_nodo'))

            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT 1 FROM brokers WHERE id = %s AND usuario_id = %s",
                (broker_id, user_id)
            )
            if not cur.fetchone():
                flash("Broker no válido", "danger")
                cur.close()
                return redirect(url_for('agregar_nodo'))

            cur.execute(
                "INSERT INTO nodos (nombre, id_dispositivo, broker_id, usuario_id) VALUES (%s, %s, %s, %s)",
                (nombre, id_dispositivo, broker_id, user_id)
            )
            mysql.connection.commit()
            cur.close()

            flash("¡Nodo agregado correctamente!", "success")
            return redirect(url_for('index'))

        except Exception as e:
            logging.error(f"Error al agregar nodo: {str(e)}")
            flash('Error al agregar el nodo. Por favor, intente nuevamente.', "danger")
            return redirect(url_for('agregar_nodo'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, dominio FROM brokers WHERE usuario_id = %s", (user_id,))
    brokers = cur.fetchall()
    cur.execute("SELECT tema FROM usuarios WHERE id = %s", (user_id,))
    tema_result = cur.fetchone()
    tema_preferido = tema_result[0] if tema_result else 0
    cur.close()

    return render_template('agregar_nodo.html', 
                           brokers=brokers,
                           tema_preferido=tema_preferido)


@app.route('/actualizar_tema', methods=['POST'])
@require_login
def actualizar_tema():
    try:
        tema = request.form.get('tema')
        if tema is not None:
            tema_valor = 1 if tema == 'dark' else 0
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE usuarios SET tema = %s WHERE id = %s",
                (tema_valor, session["user_id"])
            )
            mysql.connection.commit()
            cur.close()
            return jsonify({"success": True}), 200
        return jsonify({"error": "No se proporcionó tema"}), 400
    except Exception as e:
        logging.error(f"Error al actualizar tema: {str(e)}")
        return jsonify({"error": "Error al actualizar tema"}), 500


@app.route('/brokers')
@require_login
def listar_brokers():
    try:
        user_id = session["user_id"]
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, dominio, usuario_broker, pass_encrypted, puerto_tls "
            "FROM brokers WHERE usuario_id = %s",
            (user_id,)
        )
        filas = cur.fetchall()
        cur.close()

        brokers = []
        for fila in filas:
            id_b, dominio, usuario_b, pass_enc, puerto = fila
            try:
                pass_plain = decrypt_password(pass_enc)
            except Exception:
                pass_plain = ""
            brokers.append({
                "id":         id_b,
                "dominio":    dominio,
                "usuario":    usuario_b,
                "password":   pass_plain,
                "puerto_tls": puerto
            })

        return render_template('brokers.html',
                               username=session.get("username"),
                               brokers=brokers)
    except Exception as e:
        logging.error(f"Error al listar brokers: {str(e)}")
        flash("Error al cargar los brokers", "danger")
        return redirect(url_for('index'))


@app.route('/agregar_broker', methods=['GET', 'POST'])
@require_login
def agregar_broker():
    if request.method == "POST":
        dominio    = request.form.get("dominio")
        usuario_b  = request.form.get("usuario_broker")
        password_b = request.form.get("password_broker")
        puerto     = request.form.get("puerto_tls")

        try:
            puerto = int(puerto)
        except ValueError:
            flash("El puerto TLS debe ser un número", "danger")
            return redirect(url_for('agregar_broker'))

        pass_cifrada = encrypt_password(password_b)
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO brokers (dominio, usuario_broker, pass_encrypted, puerto_tls, usuario_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (dominio, usuario_b, pass_cifrada, puerto, session["user_id"])
            )
            mysql.connection.commit()
            cur.close()
            flash("Broker agregado correctamente", "success")
            return redirect(url_for('listar_brokers'))
        except Exception as e:
            logging.error(f"Error al agregar broker: {str(e)}")
            flash("Error al agregar el broker. Intente nuevamente.", "danger")
            return redirect(url_for('agregar_broker'))

    return render_template('agregar_broker.html',
                           tema_preferido=session.get("tema"),
                           username=session.get("username"))


@app.route('/editar_broker/<int:id_broker>', methods=['GET', 'POST'])
@require_login
def editar_broker(id_broker):
    user_id = session["user_id"]
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT dominio, usuario_broker, pass_encrypted, puerto_tls "
        "FROM brokers WHERE id = %s AND usuario_id = %s",
        (id_broker, user_id)
    )
    fila = cur.fetchone()
    if not fila:
        cur.close()
        flash("Broker no encontrado o no autorizado", "danger")
        return redirect(url_for('listar_brokers'))

    if request.method == "POST":
        dominio_n   = request.form.get("dominio")
        usuario_n   = request.form.get("usuario_broker")
        password_n  = request.form.get("password_broker")
        puerto_n    = request.form.get("puerto_tls")

        try:
            puerto_n = int(puerto_n)
        except ValueError:
            flash("El puerto TLS debe ser un número", "danger")
            cur.close()
            return redirect(url_for('editar_broker', id_broker=id_broker))

        pass_cifrada = encrypt_password(password_n)
        try:
            cur.execute(
                "UPDATE brokers SET dominio = %s, usuario_broker = %s, pass_encrypted = %s, puerto_tls = %s "
                "WHERE id = %s AND usuario_id = %s",
                (dominio_n, usuario_n, pass_cifrada, puerto_n, id_broker, user_id)
            )
            mysql.connection.commit()
            cur.close()
            flash("Broker actualizado correctamente", "success")
            return redirect(url_for('listar_brokers'))
        except Exception as e:
            logging.error(f"Error al editar broker: {str(e)}")
            flash("Error al actualizar el broker. Intente nuevamente.", "danger")
            cur.close()
            return redirect(url_for('editar_broker', id_broker=id_broker))

    dominio, usuario_b, pass_enc, puerto = fila
    try:
        pass_plain = decrypt_password(pass_enc)
    except Exception:
        pass_plain = ""
    cur.close()
    return render_template('editar_broker.html',
                           id_broker=id_broker,
                           dominio=dominio,
                           usuario_broker=usuario_b,
                           password_broker=pass_plain,
                           puerto_tls=puerto,
                           tema_preferido=session.get("tema"),
                           username=session.get("username"))

@app.route('/eliminar_broker/<int:id_broker>', methods=['POST'])
@require_login
def eliminar_broker(id_broker):
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "DELETE FROM brokers WHERE id = %s AND usuario_id = %s",
            (id_broker, session["user_id"])
        )
        mysql.connection.commit()
        cur.close()
        flash("Broker eliminado correctamente", "success")
    except Exception as e:
        logging.error(f"Error al eliminar broker: {str(e)}")
        flash("Error al eliminar el broker", "danger")
    return redirect(url_for('listar_brokers'))