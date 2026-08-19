import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'clave_secreta_bodega_tucupido'

DATABASE = 'bodega.db'

# --- CONFIGURACIÓN DE FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_view'

class Usuario(UserMixin):
    def __init__(self, id, nombre, username):
        self.id = id
        self.nombre = nombre
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, username FROM usuarios WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return Usuario(id=row['id'], nombre=row['nombre'], username=row['username'])
    return None

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')

    cursor.execute("SELECT id FROM usuarios WHERE username = 'admin'")
    if not cursor.fetchone():
        pass_hash = generate_password_hash('admin123')
        cursor.execute("INSERT INTO usuarios (nombre, username, password_hash) VALUES ('Administrador', 'admin', ?)", (pass_hash,))

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            precio_usd REAL NOT NULL,
            stock REAL NOT NULL DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            telefono TEXT,
            deuda_usd REAL DEFAULT 0.0
        )
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO clientes (id, nombre, telefono, deuda_usd) 
        VALUES (1, 'Cliente Genérico', 'N/A', 0.0)
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER DEFAULT 1,
            total_usd REAL NOT NULL,
            es_credito INTEGER DEFAULT 0,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venta_detalles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            cantidad REAL NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas (id),
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            cantidad REAL NOT NULL,
            motivo TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        )
    ''')

    # Tabla para guardar la tasa del dólar de forma persistente
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            id INTEGER PRIMARY KEY,
            tasa_dolar REAL NOT NULL
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO configuracion (id, tasa_dolar) VALUES (1, 36.5)")

    conn.commit()
    conn.close()

init_db()

# --- INYECCIÓN GLOBAL DE TASA PARA PLANTILLAS ---
@app.context_processor
def inject_tasa():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT tasa_dolar FROM configuracion WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        tasa = row['tasa_dolar'] if row else 36.5
    except Exception:
        tasa = 36.5
    return dict(tasa_actual=tasa)

# --- RUTAS DE AUTENTICACIÓN Y CONFIGURACIÓN ---

@app.route('/actualizar-tasa', methods=['POST'])
@login_required
def actualizar_tasa():
    nueva_tasa = request.form.get('tasa_dolar')
    if nueva_tasa:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE configuracion SET tasa_dolar = ? WHERE id = 1", (float(nueva_tasa),))
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for('pos_view'))

@app.route('/login', methods=['GET', 'POST'])
def login_view():
    if current_user.is_authenticated:
        return redirect(url_for('pos_view'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        conn.close()

        if user_row and check_password_hash(user_row['password_hash'], password):
            user_obj = Usuario(id=user_row['id'], nombre=user_row['nombre'], username=user_row['username'])
            login_user(user_obj)
            return redirect(url_for('pos_view'))
        else:
            flash('Usuario o contraseña incorrectos', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login_view'))

# --- RUTAS DE VISTAS PRINCIPALES ---

@app.route('/')
@login_required
def pos_view():
    return render_template('pos.html')

@app.route('/inventario', methods=['GET', 'POST'])
@login_required
def inventario_view():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        codigo = request.form.get('codigo_barras').strip()
        nombre = request.form.get('nombre').strip()
        precio_usd = float(request.form.get('precio_usd', 0))
        stock = float(request.form.get('stock', 0))

        try:
            cursor.execute('''
                INSERT INTO productos (codigo, nombre, precio_usd, stock)
                VALUES (?, ?, ?, ?)
            ''', (codigo, nombre, precio_usd, stock))
            
            prod_id = cursor.lastrowid
            
            if stock > 0:
                cursor.execute('''
                    INSERT INTO movimientos (producto_id, tipo, cantidad, motivo)
                    VALUES (?, 'ENTRADA', ?, 'Inventario Inicial')
                ''', (prod_id, stock))

            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

        return redirect(url_for('inventario_view'))

    cursor.execute("SELECT id, codigo, nombre, precio_usd as precio, stock FROM productos ORDER BY id DESC")
    productos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('inventario.html', productos=productos)

@app.route('/clientes')
@login_required
def clientes_view():
    return render_template('clientes.html')

@app.route('/dashboard')
@login_required
def dashboard_view():
    conn = get_db()
    cursor = conn.cursor()

    # Tasa obtenida de la base de datos
    cursor.execute("SELECT tasa_dolar FROM configuracion WHERE id = 1")
    tasa_row = cursor.fetchone()
    tasa_bcv = tasa_row['tasa_dolar'] if tasa_row else 36.5

    # 1. Ventas de hoy
    cursor.execute("SELECT SUM(total_usd) as total FROM ventas WHERE DATE(fecha, 'localtime') = DATE('now', 'localtime')")
    row_hoy = cursor.fetchone()
    ventas_hoy_usd = row_hoy['total'] or 0.0

    # 2. Ventas del mes
    cursor.execute("SELECT SUM(total_usd) as total FROM ventas WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')")
    row_mes = cursor.fetchone()
    ventas_mes_usd = row_mes['total'] or 0.0

    # 3. Alertas de inventario (stock <= 5)
    cursor.execute("SELECT COUNT(*) as total FROM productos WHERE stock <= 5")
    row_criticos = cursor.fetchone()
    stock_critico = row_criticos['total'] or 0

    # 4. Movimientos recientes (Entradas y Salidas)
    cursor.execute('''
        SELECT m.id, p.nombre as producto_nombre, m.tipo, m.cantidad, m.motivo, m.fecha 
        FROM movimientos m 
        JOIN productos p ON m.producto_id = p.id 
        ORDER BY m.id DESC LIMIT 15
    ''')
    movimientos = [dict(row) for row in cursor.fetchall()]

    conn.close()
    
    ventas_hoy_bs = ventas_hoy_usd * tasa_bcv
    ventas_mes_bs = ventas_mes_usd * tasa_bcv

    return render_template('dashboard.html', 
                           ventas_hoy_usd=ventas_hoy_usd, 
                           ventas_hoy_bs=ventas_hoy_bs,
                           ventas_mes_usd=ventas_mes_usd, 
                           ventas_mes_bs=ventas_mes_bs,
                           stock_critico=stock_critico,
                           movimientos=movimientos)

@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
def usuarios_view():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if nombre and username and password:
            pass_hash = generate_password_hash(password)
            try:
                cursor.execute("INSERT INTO usuarios (nombre, username, password_hash) VALUES (?, ?, ?)", (nombre, username, pass_hash))
                conn.commit()
            except sqlite3.IntegrityError:
                pass

        conn.close()
        return redirect(url_for('usuarios_view'))

    cursor.execute("SELECT id, nombre, username FROM usuarios ORDER BY id ASC")
    usuarios = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('usuarios.html', usuarios=usuarios)

# --- RUTAS API ---

@app.route('/api/producto/<codigo>')
@login_required
def buscar_producto(codigo):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, codigo, nombre, precio_usd as precio, stock FROM productos WHERE codigo = ?", (codigo.strip(),))
    row = cursor.fetchone()
    conn.close()

    if row:
        return jsonify(dict(row))
    return jsonify({"error": "Producto no encontrado"}), 404

@app.route('/api/clientes', methods=['GET'])
@login_required
def obtener_clientes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, telefono, deuda_usd FROM clientes ORDER BY id ASC")
    clientes = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(clientes)

@app.route('/api/clientes', methods=['POST'])
@login_required
def crear_cliente():
    data = request.json or {}
    nombre = data.get('nombre', '').strip()
    telefono = data.get('telefono', '').strip()

    if not nombre:
        return jsonify({"success": False, "message": "El nombre es obligatorio."}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clientes (nombre, telefono) VALUES (?, ?)", (nombre, telefono))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Cliente registrado exitosamente."})

@app.route('/api/ventas/procesar', methods=['POST'])
@login_required
def procesar_venta():
    data = request.json or {}
    items = data.get('items', [])
    cliente_id = int(data.get('cliente_id', 1))
    es_credito = bool(data.get('es_credito', False))

    if not items:
        return jsonify({"success": False, "message": "El carrito está vacío."}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        total_venta = 0.0

        for item in items:
            cursor.execute("SELECT stock, precio_usd FROM productos WHERE id = ?", (item['id'],))
            prod = cursor.fetchone()
            if not prod or prod['stock'] < item['cantidad']:
                conn.close()
                return jsonify({"success": False, "message": "Stock insuficiente."}), 400
            total_venta += prod['precio_usd'] * item['cantidad']

        cursor.execute("INSERT INTO ventas (cliente_id, total_usd, es_credito) VALUES (?, ?, ?)", (cliente_id, total_venta, 1 if es_credito else 0))
        venta_id = cursor.lastrowid

        for item in items:
            cursor.execute("SELECT precio_usd FROM productos WHERE id = ?", (item['id'],))
            precio = cursor.fetchone()['precio_usd']
            subtotal = precio * item['cantidad']

            cursor.execute("INSERT INTO venta_detalles (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)", (venta_id, item['id'], item['cantidad'], precio, subtotal))
            cursor.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (item['cantidad'], item['id']))
            cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, motivo) VALUES (?, 'SALIDA', ?, ?)", (item['id'], item['cantidad'], f'Venta #{venta_id}'))

        if es_credito and cliente_id != 1:
            cursor.execute("UPDATE clientes SET deuda_usd = deuda_usd + ? WHERE id = ?", (total_venta, cliente_id))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "venta_id": venta_id})

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    
