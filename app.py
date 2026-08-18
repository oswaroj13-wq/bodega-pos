import os
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Usa variable de entorno en producción o clave por defecto en desarrollo local
app.secret_key = os.environ.get("SECRET_KEY", "secreto_bodega_pos_pydroid")

# Ruta absoluta de la base de datos para evitar errores en Render o Pydroid 3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "bodega.db")

# Configuración Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,))
    u = cursor.fetchone()
    conn.close()
    if u:
        return User(u['id'], u['username'], u['role'])
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Acceso no autorizado. Se requieren permisos de Administrador.", "error")
            return redirect(url_for('pos_view'))
        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Tabla de Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cajero'
        )
    ''')

    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        pass_admin = generate_password_hash("admin123")
        pass_cajero = generate_password_hash("cajero123")
        cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", ("admin", pass_admin, "admin"))
        cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", ("cajero", pass_cajero, "cajero"))

    # 2. Configuración (Tasa del Día)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor REAL NOT NULL
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('tasa_dia', 36.50)")

    # 3. Productos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_barras TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            precio_usd REAL NOT NULL,
            stock REAL NOT NULL DEFAULT 0
        )
    ''')

    # 4. Ventas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            fecha DATETIME DEFAULT (datetime('now', 'localtime')),
            tasa_aplicada REAL NOT NULL,
            total_usd REAL NOT NULL,
            total_local REAL NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')

    # 5. Detalle de Ventas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            cantidad REAL NOT NULL,
            precio_usd REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas (id),
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        )
    ''')

    # 6. Movimientos de Inventario (Entradas y Salidas)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimientos_inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            cantidad REAL NOT NULL,
            motivo TEXT NOT NULL,
            fecha DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        )
    ''')

    # Datos iniciales demo si la tabla de productos está vacía
    cursor.execute("SELECT COUNT(*) FROM productos")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO productos (codigo_barras, nombre, precio_usd, stock)
            VALUES (?, ?, ?, ?)
        ''', [
            ('75010001', 'Arroz Primor 1kg', 1.20, 50.0),
            ('75010002', 'Harina PAN 1kg', 1.10, 100.0),
            ('75010003', 'Aceite Vegetal 1L', 2.50, 30.0),
            ('75010004', 'Kilo de Tomate', 1.80, 25.5),
            ('75010005', 'Kilo de Cebolla', 1.50, 18.0)
        ])
    
    conn.commit()
    conn.close()

# Inicializar base de datos
init_db()

def get_tasa_actual():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'tasa_dia'")
    row = cursor.fetchone()
    conn.close()
    return row['valor'] if row else 1.0

# ----------------- RUTAS DE AUTENTICACIÓN -----------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('pos_view'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        u = cursor.fetchone()
        conn.close()

        if u and check_password_hash(u['password'], password):
            user_obj = User(u['id'], u['username'], u['role'])
            login_user(user_obj)
            return redirect(url_for('pos_view'))
        else:
            flash("Usuario o contraseña incorrectos", "error")

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----------------- RUTAS DE VISTAS -----------------

@app.route('/')
@login_required
def pos_view():
    return render_template('pos.html')

@app.route('/inventario')
@login_required
@admin_required
def inventario_view():
    return render_template('inventario.html')

@app.route('/ventas')
@login_required
@admin_required
def ventas_view():
    return render_template('ventas.html')

@app.route('/dashboard')
@login_required
@admin_required
def dashboard_view():
    return render_template('dashboard.html')

@app.route('/usuarios')
@login_required
@admin_required
def usuarios_view():
    return render_template('usuarios.html')

# ----------------- API ENDPOINTS -----------------

@app.route('/api/tasa', methods=['GET', 'POST'])
@login_required
def api_tasa():
    if request.method == 'GET':
        return jsonify({'tasa': get_tasa_actual()})
    elif request.method == 'POST':
        if current_user.role != 'admin':
            return jsonify({'error': 'Solo el administrador puede cambiar la tasa'}), 403
            
        data = request.json
        nueva_tasa = float(data.get('tasa', 0))
        if nueva_tasa <= 0:
            return jsonify({'error': 'La tasa debe ser mayor a 0'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'tasa_dia'", (nueva_tasa,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok', 'tasa': nueva_tasa})

@app.route('/api/producto/<codigo>')
@login_required
def get_producto(codigo):
    tasa = get_tasa_actual()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM productos WHERE codigo_barras = ?", (codigo,))
    prod = cursor.fetchone()
    conn.close()

    if prod:
        p = dict(prod)
        p['precio_local'] = round(p['precio_usd'] * tasa, 2)
        return jsonify(p)
    return jsonify({'error': 'Producto no encontrado'}), 404

@app.route('/api/productos', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_productos():
    tasa = get_tasa_actual()
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM productos ORDER BY nombre ASC")
        prods = [dict(row) for row in cursor.fetchall()]
        for p in prods:
            p['precio_local'] = round(p['precio_usd'] * tasa, 2)
        conn.close()
        return jsonify(prods)

    if current_user.role != 'admin':
        return jsonify({'error': 'Requiere rol de Administrador'}), 403

    if request.method == 'POST':
        data = request.json
        try:
            stock_inicial = float(data['stock'])
            cursor.execute('''
                INSERT INTO productos (codigo_barras, nombre, precio_usd, stock)
                VALUES (?, ?, ?, ?)
            ''', (data['codigo_barras'], data['nombre'], float(data['precio_usd']), stock_inicial))
            prod_id = cursor.lastrowid

            if stock_inicial > 0:
                cursor.execute('''
                    INSERT INTO movimientos_inventario (producto_id, tipo, cantidad, motivo)
                    VALUES (?, 'ENTRADA', ?, 'Registro Inicial de Producto')
                ''', (prod_id, stock_inicial))

            conn.commit()
            conn.close()
            return jsonify({'status': 'ok'})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'El código de barras ya existe'}), 400

    elif request.method == 'PUT':
        data = request.json
        prod_id = data['id']
        nuevo_stock = float(data['stock'])

        cursor.execute("SELECT stock FROM productos WHERE id = ?", (prod_id,))
        prod_actual = cursor.fetchone()

        if prod_actual:
            stock_anterior = prod_actual['stock']
            diferencia = nuevo_stock - stock_anterior

            cursor.execute('''
                UPDATE productos SET nombre = ?, precio_usd = ?, stock = ? WHERE id = ?
            ''', (data['nombre'], float(data['precio_usd']), nuevo_stock, prod_id))

            if diferencia > 0:
                cursor.execute('''
                    INSERT INTO movimientos_inventario (producto_id, tipo, cantidad, motivo)
                    VALUES (?, 'ENTRADA', ?, 'Ajuste Manual / Reposición')
                ''', (prod_id, diferencia))
            elif diferencia < 0:
                cursor.execute('''
                    INSERT INTO movimientos_inventario (producto_id, tipo, cantidad, motivo)
                    VALUES (?, 'SALIDA', ?, 'Ajuste Manual / Desincorporación')
                ''', (prod_id, abs(diferencia)))

        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})

    elif request.method == 'DELETE':
        prod_id = request.args.get('id')
        cursor.execute("DELETE FROM productos WHERE id = ?", (prod_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})

@app.route('/api/usuarios', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_usuarios():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT id, username, role FROM usuarios ORDER BY username ASC")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(users)

    elif request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role', 'cajero')

        if not username or not password:
            conn.close()
            return jsonify({'error': 'Usuario y contraseña requeridos'}), 400

        hashed_pw = generate_password_hash(password)
        try:
            cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", 
                           (username, hashed_pw, role))
            conn.commit()
            conn.close()
            return jsonify({'status': 'ok'})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'El nombre de usuario ya existe'}), 400

    elif request.method == 'PUT':
        data = request.json
        user_id = data.get('id')
        username = data.get('username')
        role = data.get('role')
        new_password = data.get('password')

        if new_password:
            hashed_pw = generate_password_hash(new_password)
            cursor.execute("UPDATE usuarios SET username = ?, role = ?, password = ? WHERE id = ?", 
                           (username, role, hashed_pw, user_id))
        else:
            cursor.execute("UPDATE usuarios SET username = ?, role = ? WHERE id = ?", 
                           (username, role, user_id))

        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})

    elif request.method == 'DELETE':
        user_id = request.args.get('id')
        if int(user_id) == current_user.id:
            conn.close()
            return jsonify({'error': 'No puedes eliminar tu propio usuario'}), 400

        cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})

@app.route('/api/despachar', methods=['POST'])
@login_required
def despachar():
    data = request.get_json() or {}
    items = data.get('items', [])

    if not items:
        return jsonify({'error': 'El carrito está vacío'}), 400

    tasa = get_tasa_actual()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        total_usd = sum(float(item['cantidad']) * float(item['precio_usd']) for item in items)
        total_local = round(total_usd * tasa, 2)

        cursor.execute('''
            INSERT INTO ventas (usuario_id, tasa_aplicada, total_usd, total_local)
            VALUES (?, ?, ?, ?)
        ''', (current_user.id, tasa, total_usd, total_local))
        venta_id = cursor.lastrowid

        for item in items:
            prod_id = item.get('id') or item.get('producto_id')
            cant = float(item['cantidad'])
            precio = float(item['precio_usd'])

            cursor.execute('''
                INSERT INTO detalle_ventas (venta_id, producto_id, cantidad, precio_usd)
                VALUES (?, ?, ?, ?)
            ''', (venta_id, prod_id, cant, precio))

            cursor.execute('''
                UPDATE productos SET stock = stock - ? WHERE id = ?
            ''', (cant, prod_id))

            cursor.execute('''
                INSERT INTO movimientos_inventario (producto_id, tipo, cantidad, motivo)
                VALUES (?, 'SALIDA', ?, ?)
            ''', (prod_id, cant, f'Venta POS #{venta_id}'))

        conn.commit()
        return jsonify({'status': 'success', 'venta_id': venta_id, 'total_usd': total_usd, 'total_local': total_local})

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/historial-ventas')
@login_required
@admin_required
def historial_ventas():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT v.id, strftime('%d/%m/%Y %H:%M:%S', v.fecha) as fecha_formateada, v.tasa_aplicada, v.total_usd, v.total_local, u.username as cajero, COUNT(dv.id) as total_items
        FROM ventas v
        LEFT JOIN usuarios u ON v.usuario_id = u.id
        LEFT JOIN detalle_ventas dv ON v.id = dv.venta_id
        GROUP BY v.id
        ORDER BY v.fecha DESC
        LIMIT 50
    ''')
    ventas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(ventas)

@app.route('/api/movimientos-inventario')
@login_required
@admin_required
def api_movimientos_inventario():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.id, m.tipo, m.cantidad, m.motivo, strftime('%d/%m/%Y %H:%M:%S', m.fecha) as fecha_formateada, p.nombre as producto
        FROM movimientos_inventario m
        JOIN productos p ON m.producto_id = p.id
        ORDER BY m.fecha DESC
        LIMIT 50
    ''')
    movimientos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(movimientos)

@app.route('/api/metrics')
@login_required
@admin_required
def get_metrics():
    tasa = get_tasa_actual()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(total_usd) FROM ventas WHERE date(fecha) = date('now', 'localtime')")
    ventas_hoy_usd = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(total_usd) FROM ventas WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now', 'localtime')")
    ventas_mes_usd = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT COUNT(*) FROM productos WHERE stock < 5")
    stock_bajo = cursor.fetchone()[0]

    cursor.execute('''
        SELECT date(fecha) as dia, SUM(total_usd) as total
        FROM ventas
        WHERE fecha >= date('now', '-7 days', 'localtime')
        GROUP BY date(fecha)
        ORDER BY dia ASC
    ''')
    ventas_7dias = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT p.nombre, SUM(dv.cantidad) as total_vendido
        FROM detalle_ventas dv
        JOIN productos p ON dv.producto_id = p.id
        GROUP BY p.id
        ORDER BY total_vendido DESC
        LIMIT 5
    ''')
    top_productos = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({
        'tasa': tasa,
        'ventas_hoy_usd': ventas_hoy_usd,
        'ventas_hoy_local': round(ventas_hoy_usd * tasa, 2),
        'ventas_mes_usd': ventas_mes_usd,
        'ventas_mes_local': round(ventas_mes_usd * tasa, 2),
        'stock_bajo': stock_bajo,
        'ventas_7dias': ventas_7dias,
        'top_productos': top_productos
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
        
