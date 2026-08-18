import os
import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Configurado para apuntar directamente a bodega.db
DB_PATH = os.path.join(BASE_DIR, 'bodega.db')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave-secreta-bodega-2026')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute('SELECT id, username, role FROM usuarios WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(id=user['id'], username=user['username'], role=user['role'])
    return None

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Esquema ajustado a la estructura de bodega.db
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cajero'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor REAL NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_barras TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            precio_usd REAL NOT NULL,
            stock REAL NOT NULL DEFAULT 0
        )
    ''')
    
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

    # Configurar tasa del día predeterminada si no existe
    tasa = cursor.execute('SELECT * FROM configuracion WHERE clave = ?', ('tasa_dia',)).fetchone()
    if not tasa:
        cursor.execute('INSERT INTO configuracion (clave, valor) VALUES (?, ?)', ('tasa_dia', 36.50))
    
    # Crear usuario admin por defecto si no existe
    admin = cursor.execute('SELECT * FROM usuarios WHERE username = ?', ('admin',)).fetchone()
    if not admin:
        hashed = generate_password_hash('admin123')
        cursor.execute('INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)', ('admin', hashed, 'admin'))
    
    conn.commit()
    conn.close()

init_db()

# Servir manifest.json para la PWA
@app.route('/manifest.json')
def manifest():
    return send_from_directory(BASE_DIR, 'manifest.json')

# --- AUTENTICACIÓN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('pos_view'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            user_obj = User(id=user['id'], username=user['username'], role=user['role'])
            login_user(user_obj)
            return redirect(url_for('pos_view'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- VISTAS PRINCIPALES ---

@app.route('/')
@login_required
def pos_view():
    return render_template('pos.html')

@app.route('/inventario')
@login_required
def inventario_view():
    if current_user.role != 'admin':
        flash('Acceso restringido para administradores.', 'error')
        return redirect(url_for('pos_view'))
    conn = get_db()
    productos = conn.execute('SELECT id, codigo_barras AS codigo, nombre, precio_usd AS precio, stock FROM productos ORDER BY nombre ASC').fetchall()
    conn.close()
    return render_template('inventario.html', productos=productos)

@app.route('/ventas')
@login_required
def ventas_view():
    if current_user.role != 'admin':
        flash('Acceso restringido para administradores.', 'error')
        return redirect(url_for('pos_view'))
    conn = get_db()
    ventas = conn.execute('''
        SELECT v.id, v.fecha, v.total_usd AS total, v.total_local, v.tasa_aplicada, u.username 
        FROM ventas v 
        LEFT JOIN usuarios u ON v.usuario_id = u.id 
        ORDER BY v.fecha DESC
    ''').fetchall()
    conn.close()
    return render_template('ventas.html', ventas=ventas)

@app.route('/dashboard')
@login_required
def dashboard_view():
    if current_user.role != 'admin':
        flash('Acceso restringido para administradores.', 'error')
        return redirect(url_for('pos_view'))
    conn = get_db()
    total_ventas = conn.execute('SELECT SUM(total_usd) FROM ventas').fetchone()[0] or 0.0
    cant_productos = conn.execute('SELECT COUNT(*) FROM productos').fetchone()[0] or 0
    cant_ventas = conn.execute('SELECT COUNT(*) FROM ventas').fetchone()[0] or 0
    conn.close()
    return render_template('dashboard.html', total_ventas=total_ventas, cant_productos=cant_productos, cant_ventas=cant_ventas)

@app.route('/usuarios')
@login_required
def usuarios_view():
    if current_user.role != 'admin':
        flash('Acceso restringido para administradores.', 'error')
        return redirect(url_for('pos_view'))
    conn = get_db()
    usuarios = conn.execute('SELECT id, username, role FROM usuarios').fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=usuarios)

# --- API ENDPOINTS ---

@app.route('/api/productos')
@app.route('/api/productos/buscar')
@login_required
def buscar_producto():
    q = request.args.get('q', '')
    conn = get_db()
    productos = conn.execute('''
        SELECT id, codigo_barras AS codigo, nombre, precio_usd AS precio, stock 
        FROM productos 
        WHERE codigo_barras LIKE ? OR nombre LIKE ?
        LIMIT 10
    ''', (f'%{q}%', f'%{q}%')).fetchall()
    conn.close()
    return jsonify([dict(p) for p in productos])

@app.route('/api/ventas/procesar', methods=['POST'])
@login_required
def procesar_venta():
    data = request.get_json() or {}
    items = data.get('items', [])
    
    if not items:
        return jsonify({'success': False, 'message': 'El carrito está vacío'}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Obtener tasa del día de la base de datos
        tasa_row = cursor.execute("SELECT valor FROM configuracion WHERE clave = 'tasa_dia'").fetchone()
        tasa = float(tasa_row['valor']) if tasa_row else 1.0

        total_usd = sum(item['precio'] * item['cantidad'] for item in items)
        total_local = total_usd * tasa

        # Insertar venta respetando esquema de bodega.db
        cursor.execute('''
            INSERT INTO ventas (usuario_id, tasa_aplicada, total_usd, total_local)
            VALUES (?, ?, ?, ?)
        ''', (current_user.id, tasa, total_usd, total_local))
        venta_id = cursor.lastrowid
        
        for item in items:
            cursor.execute('''
                INSERT INTO detalle_ventas (venta_id, producto_id, cantidad, precio_usd)
                VALUES (?, ?, ?, ?)
            ''', (venta_id, item['id'], item['cantidad'], item['precio']))
            
            cursor.execute('''
                UPDATE productos 
                SET stock = stock - ? 
                WHERE id = ?
            ''', (item['cantidad'], item['id']))

            cursor.execute('''
                INSERT INTO movimientos_inventario (producto_id, tipo, cantidad, motivo)
                VALUES (?, 'SALIDA', ?, ?)
            ''', (item['id'], item['cantidad'], f'Venta #{venta_id}'))
            
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'venta_id': venta_id})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
