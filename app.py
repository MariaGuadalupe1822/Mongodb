from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import hashlib
import os
import io
from functools import wraps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader

app = Flask(__name__)
app.secret_key = 'clave_secreta_biblioteca_2024'

# ----------------- CONEXIÓN A MONGODB -----------------
try:
    client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    client.admin.command('ping') 

    db = client['libros']
    
    coleccion_libros = db['tipolibro']
    coleccion_usuarios = db['usuarios']
    coleccion_clientes = db['clientes']  
    coleccion_ventas = db['ventas']

    print("Conexión exitosa a MongoDB.")

except Exception as e:
    print(f"ERROR: No se pudo conectar a MongoDB. Detalle: {e}")

# ----------------- FUNCIONES AUXILIARES -----------------
def encriptar_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def cliente_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'cliente_id' not in session:
            return redirect(url_for('login_cliente'))
        return f(*args, **kwargs)
    return decorated_function

def calcular_iva(subtotal, porcentaje_iva=16):
    """Calcular IVA basado en el subtotal"""
    return subtotal * (porcentaje_iva / 100)

# ----------------- INICIALIZAR DATOS -----------------
def inicializar_datos():
    # Verificar si existe al menos un usuario administrador
    if coleccion_usuarios.count_documents({}) == 0:
        usuario_admin = {
            'nombre': 'Administrador',
            'email': 'admin@biblioteca.com',
            'password': encriptar_password('admin123'),
            'rol': 'administrador',
            'activo': True,
            'fecha_registro': datetime.now()
        }
        coleccion_usuarios.insert_one(usuario_admin)
        print("Usuario administrador creado: admin@biblioteca.com / admin123")

# ----------------- RUTAS DE AUTENTICACIÓN -----------------

@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    elif 'cliente_id' in session:
        return redirect(url_for('catalogo_cliente'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar si es administrador
        usuario = coleccion_usuarios.find_one({
            'email': email, 
            'password': encriptar_password(password),
            'activo': True
        })
        
        if usuario:
            session['usuario_id'] = str(usuario['_id'])
            session['usuario_nombre'] = usuario['nombre']
            session['usuario_rol'] = usuario['rol']
            flash('¡Bienvenido ' + usuario['nombre'] + '!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas', 'error')
    
    return render_template('login.html')

@app.route('/login-cliente', methods=['GET', 'POST'])
def login_cliente():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar si es cliente
        cliente = coleccion_clientes.find_one({
            'email': email, 
            'password': encriptar_password(password),
            'activo': True
        })
        
        if cliente:
            session['cliente_id'] = str(cliente['_id'])
            session['cliente_nombre'] = cliente['nombre']
            session['cliente_email'] = cliente['email']
            # Inicializar carrito vacío
            session['carrito'] = []
            flash('¡Bienvenido ' + cliente['nombre'] + '!', 'success')
            return redirect(url_for('catalogo_cliente'))
        else:
            flash('Credenciales incorrectas', 'error')
    
    return render_template('login_cliente.html')

@app.route('/registro-cliente', methods=['GET', 'POST'])
def registro_cliente():
    if request.method == 'POST':
        try:
            # Verificar si el email ya existe
            cliente_existente = coleccion_clientes.find_one({'email': request.form.get('email')})
            if cliente_existente:
                flash('El email ya está registrado', 'error')
                return render_template('registro_cliente.html')
            
            # Obtener la contraseña del formulario
            password = request.form.get('password')
            if not password:
                flash('La contraseña es requerida', 'error')
                return render_template('registro_cliente.html')
            
            cliente = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(password),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                },
                'fecha_registro': datetime.now(),
                'activo': True
            }
            coleccion_clientes.insert_one(cliente)
            flash('Cliente registrado exitosamente. Ahora puedes iniciar sesión.', 'success')
            return redirect(url_for('login_cliente'))
        except Exception as e:
            flash(f'Error al registrar cliente: {e}', 'error')
    
    return render_template('registro_cliente.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'success')
    return redirect(url_for('login'))

# ----------------- DASHBOARD ADMIN -----------------

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        total_libros = coleccion_libros.count_documents({})
        total_clientes = coleccion_clientes.count_documents({'activo': True})
        total_ventas = coleccion_ventas.count_documents({})
        
        inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ventas_mes = list(coleccion_ventas.find({'fecha_venta': {'$gte': inicio_mes}}))
        total_ventas_mes = sum(venta.get('total', 0) for venta in ventas_mes)
        
        libros_stock_bajo = list(coleccion_libros.find({'stock': {'$lt': 5}}))
        
        # Ventas recientes para el dashboard
        ventas_recientes = list(coleccion_ventas.find().sort('fecha_venta', -1).limit(5))
        for venta in ventas_recientes:
            if 'cliente_nombre' not in venta:
                cliente = coleccion_clientes.find_one({'_id': ObjectId(venta['cliente_id'])})
                venta['cliente_nombre'] = cliente['nombre'] if cliente else 'Cliente no encontrado'
        
        return render_template('dashboard.html',
                             total_libros=total_libros,
                             total_clientes=total_clientes,
                             total_ventas=total_ventas,
                             total_ventas_mes=total_ventas_mes,
                             libros_stock_bajo=libros_stock_bajo,
                             ventas_recientes=ventas_recientes)
    except Exception as e:
        flash(f'Error al cargar dashboard: {e}', 'error')
        return render_template('dashboard.html')

# ----------------- CRUD USUARIOS (ADMIN) -----------------

@app.route('/usuarios')
@login_required
def listar_usuarios():
    try:
        usuarios = list(coleccion_usuarios.find({'activo': True}))
        return render_template('usuarios.html', usuarios=usuarios)
    except Exception as e:
        flash(f'Error al cargar usuarios: {e}', 'error')
        return render_template('usuarios.html', usuarios=[])

@app.route('/usuarios/agregar', methods=['GET', 'POST'])
@login_required
def agregar_usuario():
    if request.method == 'POST':
        try:
            # Verificar si el email ya existe
            usuario_existente = coleccion_usuarios.find_one({'email': request.form.get('email')})
            if usuario_existente:
                flash('El email ya está registrado', 'error')
                return render_template('agregar_usuario.html')
            
            usuario = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(request.form.get('password')),
                'rol': request.form.get('rol', 'empleado'),
                'activo': True,
                'fecha_registro': datetime.now()
            }
            coleccion_usuarios.insert_one(usuario)
            flash('Usuario agregado exitosamente', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            flash(f'Error al crear el usuario: {e}', 'error')
    
    return render_template('agregar_usuario.html')

@app.route('/usuarios/editar/<id>', methods=['GET', 'POST'])
@login_required
def editar_usuario(id):
    try:
        usuario = coleccion_usuarios.find_one({'_id': ObjectId(id)})
        if not usuario:
            flash('Usuario no encontrado', 'error')
            return redirect(url_for('listar_usuarios'))
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'rol': request.form.get('rol', 'empleado')
            }
            
            # Si se proporciona una nueva contraseña, actualizarla
            nueva_password = request.form.get('password')
            if nueva_password:
                datos_actualizados['password'] = encriptar_password(nueva_password)
            
            resultado = coleccion_usuarios.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            
            if resultado.modified_count > 0:
                flash('Usuario actualizado exitosamente', 'success')
            else:
                flash('No se realizaron cambios en el usuario', 'info')
                
            return redirect(url_for('listar_usuarios'))
        
        return render_template('editar_usuario.html', usuario=usuario)
    
    except Exception as e:
        flash(f'Error al editar usuario: {str(e)}', 'error')
        return redirect(url_for('listar_usuarios'))

@app.route('/usuarios/eliminar/<id>', methods=['POST'])
@login_required
def eliminar_usuario(id):
    try:
        # No permitir eliminar el propio usuario
        if str(id) == session['usuario_id']:
            flash('No puedes eliminar tu propio usuario', 'error')
            return redirect(url_for('listar_usuarios'))
        
        coleccion_usuarios.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'activo': False}}
        )
        flash('Usuario eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar usuario: {e}', 'error')
    
    return redirect(url_for('listar_usuarios'))

# ----------------- CRUD LIBROS (ADMIN) -----------------

@app.route('/libros')
@login_required
def listar_libros():
    try:
        libros = list(coleccion_libros.find())
        return render_template('libros.html', libros=libros)
    except Exception as e:
        flash(f'Error al cargar libros: {e}', 'error')
        return render_template('libros.html', libros=[])

@app.route('/libros/agregar', methods=['GET', 'POST'])
@login_required
def agregar_libro():
    if request.method == 'POST':
        try:
            libro = {
                'nombre': request.form.get('nombre'),         
                'autor': request.form.get('autor'),
                'genero': request.form.get('genero'),         
                'stock': int(request.form.get('stock', 0)), 
                'isbn': request.form.get('isbn'),
                'anio_publicacion': int(request.form.get('anio_publicacion', 0)),
                'precio': float(request.form.get('precio', 0)),
                'descripcion': request.form.get('descripcion', ''),
                'fecha_agregado': datetime.now()
            }
            coleccion_libros.insert_one(libro)
            flash('Libro agregado exitosamente', 'success')
            return redirect(url_for('listar_libros'))
        except Exception as e:
            flash(f'Error al crear el libro: {e}', 'error')
    
    return render_template('agregar_libro.html')

@app.route('/libros/editar/<id>', methods=['GET', 'POST'])
@login_required
def editar_libro(id):
    try:
        libro = coleccion_libros.find_one({'_id': ObjectId(id)})
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),         
                'autor': request.form.get('autor'),
                'genero': request.form.get('genero'),
                'stock': int(request.form.get('stock', 0)),
                'isbn': request.form.get('isbn'),
                'anio_publicacion': int(request.form.get('anio_publicacion', 0)),
                'precio': float(request.form.get('precio', 0)),
                'descripcion': request.form.get('descripcion', '')
            }
            
            coleccion_libros.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            flash('Libro actualizado exitosamente', 'success')
            return redirect(url_for('listar_libros'))
        
        return render_template('editar_libro.html', libro=libro)
    
    except Exception as e:
        flash(f'Error: {e}', 'error')
        return redirect(url_for('listar_libros'))

@app.route('/libros/eliminar/<id>', methods=['POST'])
@login_required
def eliminar_libro(id):
    try:
        coleccion_libros.delete_one({'_id': ObjectId(id)})
        flash('Libro eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar libro: {e}', 'error')
    
    return redirect(url_for('listar_libros'))

# ----------------- CRUD CLIENTES (ADMIN) -----------------

@app.route('/clientes')
@login_required
def listar_clientes():
    try:
        clientes = list(coleccion_clientes.find({'activo': True}))
        return render_template('clientes.html', clientes=clientes)
    except Exception as e:
        flash(f'Error al cargar clientes: {e}', 'error')
        return render_template('clientes.html', clientes=[])

@app.route('/clientes/agregar', methods=['GET', 'POST'])
@login_required
def agregar_cliente():
    if request.method == 'POST':
        try:
            # Obtener la contraseña del formulario
            password = request.form.get('password')
            if not password:
                password = 'cliente123'  # Contraseña por defecto
            
            cliente = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(password),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                },
                'fecha_registro': datetime.now(),
                'activo': True
            }
            coleccion_clientes.insert_one(cliente)
            flash('Cliente agregado exitosamente', 'success')
            return redirect(url_for('listar_clientes'))
        except Exception as e:
            flash(f'Error al agregar cliente: {e}', 'error')
    
    return render_template('agregar_cliente.html')

@app.route('/clientes/editar/<id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    try:
        cliente = coleccion_clientes.find_one({'_id': ObjectId(id)})
        if not cliente:
            flash('Cliente no encontrado', 'error')
            return redirect(url_for('listar_clientes'))
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                }
            }
            
            # Si se proporciona una nueva contraseña, actualizarla
            nueva_password = request.form.get('password')
            if nueva_password:
                datos_actualizados['password'] = encriptar_password(nueva_password)
            
            resultado = coleccion_clientes.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            
            if resultado.modified_count > 0:
                flash('Cliente actualizado exitosamente', 'success')
            else:
                flash('No se realizaron cambios en el cliente', 'info')
                
            return redirect(url_for('listar_clientes'))
        
        return render_template('editar_cliente.html', cliente=cliente)
    
    except Exception as e:
        flash(f'Error al editar cliente: {str(e)}', 'error')
        return redirect(url_for('listar_clientes'))

@app.route('/clientes/eliminar/<id>', methods=['POST'])
@login_required
def eliminar_cliente(id):
    try:
        coleccion_clientes.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'activo': False}}
        )
        flash('Cliente eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar cliente: {e}', 'error')
    
    return redirect(url_for('listar_clientes'))

# ----------------- VENTAS CON IVA -----------------

@app.route('/ventas')
@login_required
def listar_ventas():
    try:
        # CORREGIDO: Convertir cursor a lista correctamente
        ventas_cursor = coleccion_ventas.find().sort('fecha_venta', -1)
        ventas = list(ventas_cursor)
        
        for venta in ventas:
            # Asegurarse de que tenemos información del cliente
            if 'cliente_nombre' not in venta:
                cliente = coleccion_clientes.find_one({'_id': ObjectId(venta['cliente_id'])})
                if cliente:
                    venta['cliente_nombre'] = cliente['nombre']
                    venta['cliente_email'] = cliente['email']
                    venta['cliente_telefono'] = cliente.get('telefono', '')
                else:
                    venta['cliente_nombre'] = 'Cliente no encontrado'
                    venta['cliente_email'] = ''
                    venta['cliente_telefono'] = ''
            
            # Asegurarse de que tenemos información del usuario
            if 'usuario_nombre' not in venta and 'usuario_id' in venta:
                usuario = coleccion_usuarios.find_one({'_id': ObjectId(venta['usuario_id'])})
                venta['usuario_nombre'] = usuario['nombre'] if usuario else 'Usuario no encontrado'
        
        return render_template('ventas.html', ventas=ventas)
    except Exception as e:
        flash(f'Error al cargar ventas: {str(e)}', 'error')
        return render_template('ventas.html', ventas=[])

@app.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    if request.method == 'POST':
        try:
            cliente_id = request.form.get('cliente_id')
            if not cliente_id:
                flash('Selecciona un cliente', 'error')
                return redirect(url_for('nueva_venta'))
            
            items = []
            libro_ids = request.form.getlist('libro_id[]')
            cantidades = request.form.getlist('cantidad[]')
            
            subtotal_venta = 0
            
            for i, libro_id in enumerate(libro_ids):
                if libro_id and cantidades[i] and int(cantidades[i]) > 0:
                    cantidad = int(cantidades[i])
                    libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
                    
                    if libro and libro.get('stock', 0) >= cantidad:
                        precio = libro.get('precio', 0)
                        subtotal = precio * cantidad
                        subtotal_venta += subtotal
                        
                        # Guardar información completa del libro
                        items.append({
                            'libro_id': str(libro['_id']),
                            'titulo': libro['nombre'],
                            'autor': libro.get('autor', ''),
                            'genero': libro.get('genero', ''),
                            'isbn': libro.get('isbn', ''),
                            'cantidad': cantidad,
                            'precio_unitario': precio,
                            'subtotal': subtotal
                        })
                        
                        # Actualizar stock
                        nuevo_stock = libro['stock'] - cantidad
                        coleccion_libros.update_one(
                            {'_id': ObjectId(libro_id)},
                            {'$set': {'stock': nuevo_stock}}
                        )
                    else:
                        libro_nombre = libro['nombre'] if libro else 'Libro desconocido'
                        flash(f'Stock insuficiente para {libro_nombre}', 'error')
                        return redirect(url_for('nueva_venta'))
            
            if not items:
                flash('Agrega al menos un libro a la venta', 'error')
                return redirect(url_for('nueva_venta'))
            
            # Calcular IVA y total
            iva_venta = calcular_iva(subtotal_venta)
            total_con_iva = subtotal_venta + iva_venta
            
            # Obtener información completa del cliente
            cliente = coleccion_clientes.find_one({'_id': ObjectId(cliente_id)})
            
            # Crear venta con información completa e IVA
            venta = {
                'cliente_id': cliente_id,
                'cliente_nombre': cliente['nombre'] if cliente else 'Cliente no encontrado',
                'cliente_email': cliente['email'] if cliente else '',
                'cliente_telefono': cliente.get('telefono', ''),
                'usuario_id': session['usuario_id'],
                'usuario_nombre': session['usuario_nombre'],
                'items': items,
                'subtotal': subtotal_venta,
                'iva': iva_venta,
                'total': total_con_iva,
                'fecha_venta': datetime.now(),
                'estado': 'completada',
                'tipo': 'presencial'
            }
            
            resultado = coleccion_ventas.insert_one(venta)
            flash(f'Venta registrada exitosamente! Total con IVA: ${total_con_iva:.2f}', 'success')
            return redirect(url_for('ver_venta', id=resultado.inserted_id))
            
        except Exception as e:
            flash(f'Error al procesar venta: {str(e)}', 'error')
    
    clientes = list(coleccion_clientes.find({'activo': True}))
    libros = list(coleccion_libros.find({'stock': {'$gt': 0}}))
    return render_template('nueva_venta.html', clientes=clientes, libros=libros)

@app.route('/ventas/<id>')
@login_required
def ver_venta(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
        if not venta:
            flash('Venta no encontrada', 'error')
            return redirect(url_for('listar_ventas'))
        
        return render_template('ver_venta.html', venta=venta)
    except Exception as e:
        flash(f'Error al cargar venta: {e}', 'error')
        return redirect(url_for('listar_ventas'))

@app.route('/ventas/<id>/comprobante')
@login_required
def comprobante_venta(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
        if not venta:
            return "Venta no encontrada", 404
        
        # Crear PDF
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Configuración inicial
        pdf.setTitle(f"Comprobante de Venta - {venta['_id']}")
        
        # Encabezado
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(100, height - 50, "BIBLIOTECA DIGITAL")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, height - 70, "COMPROBANTE DE VENTA")
        pdf.line(100, height - 75, 500, height - 75)
        
        # Información de la venta
        y_position = height - 100
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DE LA VENTA:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Folio: {str(venta['_id'])}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Fecha: {venta['fecha_venta'].strftime('%d/%m/%Y')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Hora: {venta['fecha_venta'].strftime('%H:%M:%S')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Estado: {venta.get('estado', 'Completada')}")
        
        # Información del cliente
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL CLIENTE:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Nombre: {venta.get('cliente_nombre', 'N/A')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Email: {venta.get('cliente_email', 'N/A')}")
        if venta.get('cliente_telefono'):
            y_position -= 15
            pdf.drawString(100, y_position, f"Teléfono: {venta['cliente_telefono']}")
        
        # Información del vendedor
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL VENDEDOR:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Atendió: {venta.get('usuario_nombre', 'N/A')}")
        
        # Tabla de productos
        y_position -= 30
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "DETALLE DE PRODUCTOS:")
        
        # Encabezados de la tabla
        y_position -= 20
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(100, y_position, "Producto")
        pdf.drawString(300, y_position, "Cant.")
        pdf.drawString(350, y_position, "Precio Unit.")
        pdf.drawString(450, y_position, "Subtotal")
        
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        y_position -= 10
        
        # Items de la venta
        pdf.setFont("Helvetica", 9)
        for item in venta.get('items', []):
            if y_position < 150:  # Nueva página si es necesario
                pdf.showPage()
                y_position = height - 50
                pdf.setFont("Helvetica", 9)
            
            # Título del libro
            titulo = item['titulo']
            if len(titulo) > 40:
                titulo = titulo[:37] + "..."
            
            pdf.drawString(100, y_position, titulo)
            pdf.drawString(300, y_position, str(item['cantidad']))
            pdf.drawString(350, y_position, f"${item['precio_unitario']:.2f}")
            pdf.drawString(450, y_position, f"${item['subtotal']:.2f}")
            
            # Información adicional del libro
            if y_position > 160:
                info_extra = f"Autor: {item.get('autor', 'N/A')}"
                if len(info_extra) > 50:
                    info_extra = info_extra[:47] + "..."
                y_position -= 12
                pdf.setFont("Helvetica-Oblique", 8)
                pdf.drawString(100, y_position, info_extra)
                pdf.setFont("Helvetica", 9)
            
            y_position -= 20
        
        # Línea separadora
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        
        # Totales
        subtotal = venta.get('subtotal', 0)
        iva = venta.get('iva', 0)
        total = venta.get('total', 0)
        
        y_position -= 20
        pdf.setFont("Helvetica", 10)
        pdf.drawString(350, y_position, f"Subtotal: ${subtotal:.2f}")
        y_position -= 15
        pdf.drawString(350, y_position, f"IVA (16%): ${iva:.2f}")
        y_position -= 15
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(350, y_position, f"TOTAL: ${total:.2f}")
        
        # Pie de página con agradecimiento
        y_position -= 40
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(100, y_position, "¡Gracias por su compra en Biblioteca Digital!")
        y_position -= 15
        pdf.drawString(100, y_position, "Esperamos volver a servirle pronto.")
        y_position -= 15
        pdf.drawString(100, y_position, "Sistema de Gestión de Libros - Venta segura y confiable")
        
        pdf.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"comprobante_venta_{id}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return f"Error al generar comprobante: {e}", 500

# ----------------- CLIENTE - CATÁLOGO Y CARRITO CON IVA -----------------

@app.route('/catalogo')
@cliente_required
def catalogo_cliente():
    try:
        libros = list(coleccion_libros.find({'stock': {'$gt': 0}}))
        # Inicializar carrito si no existe
        if 'carrito' not in session:
            session['carrito'] = []
        return render_template('catalogo_cliente.html', libros=libros)
    except Exception as e:
        flash(f'Error al cargar catálogo: {e}', 'error')
        return render_template('catalogo_cliente.html', libros=[])

@app.route('/carrito/agregar', methods=['POST'])
@cliente_required
def agregar_carrito():
    try:
        libro_id = request.form.get('libro_id')
        cantidad = int(request.form.get('cantidad', 1))
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            return jsonify({'success': False, 'message': 'Libro no encontrado'})
        
        if libro.get('stock', 0) < cantidad:
            return jsonify({'success': False, 'message': 'Stock insuficiente'})
        
        # Inicializar carrito si no existe
        if 'carrito' not in session:
            session['carrito'] = []
        
        # Verificar si el libro ya está en el carrito
        carrito = session['carrito']
        libro_en_carrito = None
        for item in carrito:
            if item['libro_id'] == libro_id:
                libro_en_carrito = item
                break
        
        if libro_en_carrito:
            # Actualizar cantidad si ya está en el carrito
            nueva_cantidad = libro_en_carrito['cantidad'] + cantidad
            if nueva_cantidad > libro['stock']:
                return jsonify({'success': False, 'message': 'Stock insuficiente para la cantidad solicitada'})
            libro_en_carrito['cantidad'] = nueva_cantidad
            libro_en_carrito['subtotal'] = libro['precio'] * nueva_cantidad
        else:
            # Agregar nuevo item al carrito
            carrito.append({
                'libro_id': libro_id,
                'titulo': libro['nombre'],
                'autor': libro.get('autor', ''),
                'precio': libro['precio'],
                'cantidad': cantidad,
                'subtotal': libro['precio'] * cantidad
            })
        
        session['carrito'] = carrito
        session.modified = True
        
        return jsonify({
            'success': True, 
            'message': 'Libro agregado al carrito',
            'carrito_count': len(carrito)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/carrito')
@cliente_required
def ver_carrito():
    try:
        carrito = session.get('carrito', [])
        subtotal = sum(item['subtotal'] for item in carrito)
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        return render_template('carrito.html', carrito=carrito, subtotal=subtotal, iva=iva, total=total)
    except Exception as e:
        flash(f'Error al cargar carrito: {e}', 'error')
        return render_template('carrito.html', carrito=[], subtotal=0, iva=0, total=0)

@app.route('/carrito/actualizar', methods=['POST'])
@cliente_required
def actualizar_carrito():
    try:
        libro_id = request.form.get('libro_id')
        nueva_cantidad = int(request.form.get('cantidad', 1))
        
        if nueva_cantidad <= 0:
            return jsonify({'success': False, 'message': 'La cantidad debe ser mayor a 0'})
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            return jsonify({'success': False, 'message': 'Libro no encontrado'})
        
        if libro.get('stock', 0) < nueva_cantidad:
            return jsonify({'success': False, 'message': 'Stock insuficiente'})
        
        carrito = session.get('carrito', [])
        for item in carrito:
            if item['libro_id'] == libro_id:
                item['cantidad'] = nueva_cantidad
                item['subtotal'] = libro['precio'] * nueva_cantidad
                break
        
        session['carrito'] = carrito
        session.modified = True
        
        subtotal = sum(item['subtotal'] for item in carrito)
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        
        return jsonify({
            'success': True, 
            'message': 'Carrito actualizado',
            'subtotal': subtotal,
            'iva': iva,
            'total': total
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/carrito/eliminar/<libro_id>', methods=['POST'])
@cliente_required
def eliminar_del_carrito(libro_id):
    try:
        carrito = session.get('carrito', [])
        carrito = [item for item in carrito if item['libro_id'] != libro_id]
        session['carrito'] = carrito
        session.modified = True
        
        flash('Libro eliminado del carrito', 'success')
        return redirect(url_for('ver_carrito'))
        
    except Exception as e:
        flash(f'Error al eliminar del carrito: {e}', 'error')
        return redirect(url_for('ver_carrito'))

@app.route('/carrito/vaciar', methods=['POST'])
@cliente_required
def vaciar_carrito():
    try:
        session['carrito'] = []
        session.modified = True
        flash('Carrito vaciado', 'success')
        return redirect(url_for('ver_carrito'))
    except Exception as e:
        flash(f'Error al vaciar carrito: {e}', 'error')
        return redirect(url_for('ver_carrito'))

@app.route('/carrito/comprar', methods=['POST'])
@cliente_required
def comprar_carrito():
    try:
        carrito = session.get('carrito', [])
        if not carrito:
            flash('El carrito está vacío', 'error')
            return redirect(url_for('ver_carrito'))
        
        items = []
        subtotal_venta = 0
        
        # Verificar stock y preparar items
        for item_carrito in carrito:
            libro = coleccion_libros.find_one({'_id': ObjectId(item_carrito['libro_id'])})
            if not libro:
                flash(f'Libro {item_carrito["titulo"]} no encontrado', 'error')
                return redirect(url_for('ver_carrito'))
            
            if libro.get('stock', 0) < item_carrito['cantidad']:
                flash(f'Stock insuficiente para {libro["nombre"]}', 'error')
                return redirect(url_for('ver_carrito'))
            
            items.append({
                'libro_id': str(libro['_id']),
                'titulo': libro['nombre'],
                'autor': libro.get('autor', ''),
                'genero': libro.get('genero', ''),
                'isbn': libro.get('isbn', ''),
                'cantidad': item_carrito['cantidad'],
                'precio_unitario': libro['precio'],
                'subtotal': item_carrito['subtotal']
            })
            
            subtotal_venta += item_carrito['subtotal']
            
            # Actualizar stock
            nuevo_stock = libro['stock'] - item_carrito['cantidad']
            coleccion_libros.update_one(
                {'_id': ObjectId(item_carrito['libro_id'])},
                {'$set': {'stock': nuevo_stock}}
            )
        
        # Calcular IVA y total
        iva_venta = calcular_iva(subtotal_venta)
        total_venta = subtotal_venta + iva_venta
        
        # Crear venta con información completa e IVA
        venta = {
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'cliente_email': session['cliente_email'],
            'items': items,
            'subtotal': subtotal_venta,
            'iva': iva_venta,
            'total': total_venta,
            'fecha_venta': datetime.now(),
            'estado': 'completada',
            'tipo': 'online'
        }
        
        resultado = coleccion_ventas.insert_one(venta)
        
        # Vaciar carrito después de la compra
        session['carrito'] = []
        session.modified = True
        
        flash(f'¡Compra realizada exitosamente! Total con IVA: ${total_venta:.2f}', 'success')
        return redirect(url_for('ver_compra', id=resultado.inserted_id))
        
    except Exception as e:
        flash(f'Error al procesar compra: {e}', 'error')
        return redirect(url_for('ver_carrito'))

@app.route('/comprar-directo', methods=['POST'])
@cliente_required
def comprar_directo():
    try:
        libro_id = request.form.get('libro_id')
        cantidad = int(request.form.get('cantidad', 1))
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            flash('Libro no encontrado', 'error')
            return redirect(url_for('catalogo_cliente'))
        
        if libro.get('stock', 0) < cantidad:
            flash('Stock insuficiente', 'error')
            return redirect(url_for('catalogo_cliente'))
        
        # Crear venta con información completa
        subtotal = libro.get('precio', 0) * cantidad
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        
        items = [{
            'libro_id': str(libro['_id']),
            'titulo': libro['nombre'],
            'autor': libro.get('autor', ''),
            'genero': libro.get('genero', ''),
            'isbn': libro.get('isbn', ''),
            'cantidad': cantidad,
            'precio_unitario': libro.get('precio', 0),
            'subtotal': subtotal
        }]
        
        venta = {
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'cliente_email': session['cliente_email'],
            'items': items,
            'subtotal': subtotal,
            'iva': iva,
            'total': total,
            'fecha_venta': datetime.now(),
            'estado': 'completada',
            'tipo': 'online'
        }
        
        # Actualizar stock
        nuevo_stock = libro['stock'] - cantidad
        coleccion_libros.update_one(
            {'_id': ObjectId(libro_id)},
            {'$set': {'stock': nuevo_stock}}
        )
        
        resultado = coleccion_ventas.insert_one(venta)
        flash(f'¡Compra realizada exitosamente! Total con IVA: ${total:.2f}', 'success')
        return redirect(url_for('ver_compra', id=resultado.inserted_id))
        
    except Exception as e:
        flash(f'Error al procesar compra: {e}', 'error')
        return redirect(url_for('catalogo_cliente'))

# ----------------- MIS COMPRAS - CORREGIDA COMPLETAMENTE -----------------

@app.route('/mis-compras')
@cliente_required
def mis_compras():
    try:
        # CORREGIDO: Convertir el cursor a lista correctamente
        ventas_cursor = coleccion_ventas.find({'cliente_id': session['cliente_id']})
        ventas = list(ventas_cursor)  # Convertir cursor a lista
        
        # Ordenar por fecha descendente
        ventas.sort(key=lambda x: x['fecha_venta'], reverse=True)
        
        return render_template('mis_compras.html', ventas=ventas)
    except Exception as e:
        flash(f'Error al cargar compras: {str(e)}', 'error')
        return render_template('mis_compras.html', ventas=[])

@app.route('/mi-compra/<id>')
@cliente_required
def ver_compra(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id), 'cliente_id': session['cliente_id']})
        if not venta:
            flash('Compra no encontrada', 'error')
            return redirect(url_for('mis_compras'))
        
        return render_template('ver_compra.html', venta=venta)
    except Exception as e:
        flash(f'Error al cargar compra: {e}', 'error')
        return redirect(url_for('mis_compras'))

# ----------------- COMPROBANTE PARA CLIENTES -----------------

@app.route('/mi-compra/<id>/comprobante')
@cliente_required
def comprobante_cliente(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id), 'cliente_id': session['cliente_id']})
        if not venta:
            flash('Compra no encontrada', 'error')
            return redirect(url_for('mis_compras'))
        
        # Crear PDF
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Configuración inicial
        pdf.setTitle(f"Comprobante de Compra - {venta['_id']}")
        
        # Encabezado
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(100, height - 50, "BIBLIOTECA DIGITAL")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, height - 70, "COMPROBANTE DE COMPRA")
        pdf.line(100, height - 75, 500, height - 75)
        
        # Información de la compra
        y_position = height - 100
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DE LA COMPRA:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Folio: {str(venta['_id'])}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Fecha: {venta['fecha_venta'].strftime('%d/%m/%Y')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Hora: {venta['fecha_venta'].strftime('%H:%M:%S')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Estado: {venta.get('estado', 'Completada')}")
        
        # Información del cliente
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL CLIENTE:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Nombre: {venta.get('cliente_nombre', 'N/A')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Email: {venta.get('cliente_email', 'N/A')}")
        
        # Tabla de productos
        y_position -= 30
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "DETALLE DE PRODUCTOS:")
        
        # Encabezados de la tabla
        y_position -= 20
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(100, y_position, "Producto")
        pdf.drawString(300, y_position, "Cant.")
        pdf.drawString(350, y_position, "Precio Unit.")
        pdf.drawString(450, y_position, "Subtotal")
        
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        y_position -= 10
        
        # Items de la venta
        pdf.setFont("Helvetica", 9)
        for item in venta.get('items', []):
            if y_position < 150:  # Nueva página si es necesario
                pdf.showPage()
                y_position = height - 50
                pdf.setFont("Helvetica", 9)
            
            # Título del libro
            titulo = item['titulo']
            if len(titulo) > 40:
                titulo = titulo[:37] + "..."
            
            pdf.drawString(100, y_position, titulo)
            pdf.drawString(300, y_position, str(item['cantidad']))
            pdf.drawString(350, y_position, f"${item['precio_unitario']:.2f}")
            pdf.drawString(450, y_position, f"${item['subtotal']:.2f}")
            
            y_position -= 20
        
        # Línea separadora
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        
        # Totales
        subtotal = venta.get('subtotal', 0)
        iva = venta.get('iva', 0)
        total = venta.get('total', 0)
        
        y_position -= 20
        pdf.setFont("Helvetica", 10)
        pdf.drawString(350, y_position, f"Subtotal: ${subtotal:.2f}")
        y_position -= 15
        pdf.drawString(350, y_position, f"IVA (16%): ${iva:.2f}")
        y_position -= 15
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(350, y_position, f"TOTAL: ${total:.2f}")
        
        # Pie de página con agradecimiento
        y_position -= 40
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(100, y_position, "¡Gracias por su compra en Biblioteca Digital!")
        y_position -= 15
        pdf.drawString(100, y_position, "Esperamos volver a servirle pronto.")
        y_position -= 15
        pdf.drawString(100, y_position, "Para consultas: contacto@bibliotecadigital.com")
        
        pdf.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"comprobante_compra_{id}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return f"Error al generar comprobante: {e}", 500

# ----------------- INICIALIZACIÓN -----------------

if __name__ == '__main__':
    inicializar_datos()
    app.run(debug=True, host='0.0.0.0', port=5000)

