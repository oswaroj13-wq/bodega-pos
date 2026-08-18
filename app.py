import os
import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')

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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cajero'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            precio REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total REAL NOT NULL,
            usuario_id INTEGER,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas (id),
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        )
    ''')
    
    # Crear usuario admin por defecto si no existe
    admin = cursor.execute('SELECT * FROM usuarios WHERE username = ?', ('admin',)).fetchone()
    if not admin:
        hashed = generate_password_hash('admin123')
        cursor.execute('INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)', ('admin', hashed, 'admin'))
    
    conn.commit()
    conn.close()

init_db()

# Ruta para servir el manifest.json de la PWA
@app.route('/manifest.json')
def manifest():
    return send_from_directory(BASE_DIR, 'manifest.json')

# --- RUTAS DE AUTENTICACIÓN ---

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
    productos = conn.execute('SELECT * FROM productos ORDER BY nombre ASC').fetchall()
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
        SELECT v.id, v.fecha, v.total, u.username 
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
    total_ventas = conn.execute('SELECT SUM(total) FROM ventas').fetchone()[0] or 0.0
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

# --- API ENDPOINTS (POS / OPERACIONES) ---

@app.route('/api/productos/buscar')
@login_required
def buscar_producto():
    q = request.args.get('q', '')
    conn = get_db()
    productos = conn.execute('''
        SELECT id, codigo, nombre, precio, stock 
        FROM productos 
        WHERE codigo LIKE ? OR nombre LIKE ?
        LIMIT 10
    ''', (f'%{q}%', f'%{q}%')).fetchall()
    conn.close()
    return jsonify([dict(p) for p in productos])

@app.route('/api/ventas/procesar', methods=['POST'])
@login_required
def procesar_venta():
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({'success': False, 'message': 'El carrito está vacío'}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        total = sum(item['precio'] * item['cantidad'] for item in items)
        cursor.execute('INSERT INTO ventas (total, usuario_id) VALUES (?, ?)', (total, current_user.id))
        venta_id = cursor.lastrowid
        
        for item in items:
            cursor.execute('''
                INSERT INTO detalle_ventas (venta_id, producto_id, cantidad, precio_unitario)
                VALUES (?, ?, ?, ?)
            ''', (venta_id, item['id'], item['cantidad'], item['precio']))
            
            cursor.execute('''
                UPDATE productos 
                SET stock = stock - ? 
                WHERE id = ?
            ''', (item['cantidad'], item['id']))
            
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'venta_id': venta_id})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
