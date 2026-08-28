import csv
import io
import json
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time as time_cls

app = Flask(__name__)

# Configuración de conexión a MySQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:wilmer@localhost/db_asistencia_tjefferson'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'cambia-esta-clave-por-una-segura'

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Debes iniciar sesión para acceder a esta página.'
login_manager.login_message_category = 'warning'


# ============================
# Modelos
# ============================
class Seccion(db.Model):
    __tablename__ = 'secciones'
    id_seccion = db.Column(db.Integer, primary_key=True, autoincrement=True)
    especialidad = db.Column(db.String(100), nullable=False)
    codigo_seccion = db.Column(db.String(10), nullable=False, unique=True)
    grado = db.Column(db.SmallInteger)


class Responsable(db.Model):
    __tablename__ = 'responsables'
    id_responsable = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre_completo = db.Column(db.String(150), nullable=False)
    dui = db.Column(db.String(10), nullable=False, unique=True)
    parentesco = db.Column(db.String(50), nullable=False)
    telefono = db.Column(db.String(15))


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id_usuario = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre_completo = db.Column(db.String(150), nullable=False)
    correo = db.Column(db.String(150), nullable=False, unique=True)
    nombre_usuario = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default='empleado')
    activo = db.Column(db.Boolean, nullable=False, default=True)

    def get_id(self):
        return str(self.id_usuario)

    def set_password(self, password):
        self.password_hash = password

    def check_password(self, password):
        return self.password_hash == password


class Alumno(db.Model):
    __tablename__ = 'alumnos'
    id_alumno = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre_completo = db.Column(db.String(150), nullable=False)
    nie = db.Column(db.String(15), nullable=False, unique=True)
    genero = db.Column(db.String(1), nullable=False, default='M')  # 'M' o 'F'
    id_seccion = db.Column(db.Integer, db.ForeignKey('secciones.id_seccion'), nullable=False)
    id_responsable = db.Column(db.Integer, db.ForeignKey('responsables.id_responsable'), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    seccion = db.relationship('Seccion', backref='alumnos')
    responsable = db.relationship('Responsable', backref='alumnos')


class Asistencia(db.Model):
    __tablename__ = 'asistencias'
    id_asistencia = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_alumno = db.Column(db.Integer, db.ForeignKey('alumnos.id_alumno'), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    entrada_manana = db.Column(db.DateTime, nullable=True)
    salida_manana = db.Column(db.DateTime, nullable=True)
    entrada_tarde = db.Column(db.DateTime, nullable=True)
    salida_tarde = db.Column(db.DateTime, nullable=True)

    alumno = db.relationship('Alumno', backref='asistencias')

    __table_args__ = (db.UniqueConstraint('id_alumno', 'fecha', name='uq_alumno_fecha'),)


class Asignatura(db.Model):
    __tablename__ = 'asignaturas'
    id_asignatura = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)


class AsignacionDocente(db.Model):
    """Vincula a un docente con una sección + asignatura, y sus permisos extra en ese ámbito."""
    __tablename__ = 'asignaciones_docente'
    id_asignacion = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    id_seccion = db.Column(db.Integer, db.ForeignKey('secciones.id_seccion'), nullable=False)
    id_asignatura = db.Column(db.Integer, db.ForeignKey('asignaturas.id_asignatura'), nullable=False)

    # Permisos granulares que el Administrador puede otorgar a este docente
    # únicamente para esta combinación de sección + asignatura.
    puede_reportes = db.Column(db.Boolean, nullable=False, default=False)
    puede_editar = db.Column(db.Boolean, nullable=False, default=False)
    puede_eliminar = db.Column(db.Boolean, nullable=False, default=False)

    usuario = db.relationship('Usuario', backref='asignaciones')
    seccion = db.relationship('Seccion', backref='asignaciones_docente')
    asignatura = db.relationship('Asignatura', backref='asignaciones')

    __table_args__ = (
        db.UniqueConstraint('id_usuario', 'id_seccion', 'id_asignatura', name='uq_docente_seccion_asignatura'),
    )


class AsistenciaMateria(db.Model):
    """Asistencia por clase: un registro por alumno + materia + día (Presente/Ausente/Tardanza).
    Es independiente del control de entrada/salida general (tabla `asistencias`)."""
    __tablename__ = 'asistencias_materia'
    id_asistencia_materia = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_alumno = db.Column(db.Integer, db.ForeignKey('alumnos.id_alumno'), nullable=False)
    id_seccion = db.Column(db.Integer, db.ForeignKey('secciones.id_seccion'), nullable=False)
    id_asignatura = db.Column(db.Integer, db.ForeignKey('asignaturas.id_asignatura'), nullable=False)
    id_docente = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    estado = db.Column(db.String(10), nullable=False, default='presente')  # presente | ausente | tardanza
    registrado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)

    alumno = db.relationship('Alumno', backref='asistencias_materia')
    seccion = db.relationship('Seccion')
    asignatura = db.relationship('Asignatura')
    docente = db.relationship('Usuario')

    __table_args__ = (
        db.UniqueConstraint('id_alumno', 'id_asignatura', 'fecha', name='uq_alumno_materia_fecha'),
    )


ESTADOS_ASISTENCIA_MATERIA = {
    'presente': {'etiqueta': 'Presente', 'color': 'success', 'icono': 'bi-check-circle-fill'},
    'ausente': {'etiqueta': 'Ausente', 'color': 'danger', 'icono': 'bi-x-circle-fill'},
    'tardanza': {'etiqueta': 'Tardanza', 'color': 'warning', 'icono': 'bi-clock-fill'},
}


class ConfiguracionHorario(db.Model):
    """Ventanas de tiempo válidas para cada tipo de marcación (entrada/salida, mañana/tarde)."""
    __tablename__ = 'configuracion_horarios'
    id_config = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campo = db.Column(db.String(20), nullable=False, unique=True)
    etiqueta = db.Column(db.String(50), nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=True)  # NULL = "en adelante" (sin límite superior)


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


# ============================
# Utilidades de Roles y Permisos
# ============================
def es_admin():
    return current_user.is_authenticated and current_user.rol == 'admin'


def es_docente():
    return current_user.is_authenticated and current_user.rol == 'docente'


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not es_admin():
            flash('No tienes permisos de administrador para acceder a esta sección.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


def secciones_ids_del_docente(id_usuario):
    """IDs de sección donde el usuario tiene alguna asignación como docente."""
    filas = AsignacionDocente.query.filter_by(id_usuario=id_usuario).all()
    return {f.id_seccion for f in filas}


def puede_ver_reportes_seccion(id_seccion):
    """¿El usuario actual puede generar reportes para esta sección?"""
    if es_admin():
        return True
    if not id_seccion:
        return False
    return AsignacionDocente.query.filter_by(
        id_usuario=current_user.id_usuario, id_seccion=id_seccion, puede_reportes=True
    ).first() is not None


def combinaciones_seccion_materia_del_docente(id_usuario):
    """Pares (sección, materia) que el docente tiene asignados, para poblar el
    selector de 'Pasar asistencia por materia'."""
    filas = (
        AsignacionDocente.query
        .join(Seccion, AsignacionDocente.id_seccion == Seccion.id_seccion)
        .join(Asignatura, AsignacionDocente.id_asignatura == Asignatura.id_asignatura)
        .filter(AsignacionDocente.id_usuario == id_usuario)
        .order_by(Seccion.grado, Seccion.codigo_seccion, Asignatura.nombre)
        .all()
    )
    return filas


def puede_tomar_asistencia_materia(id_seccion, id_asignatura):
    """¿El usuario actual puede pasar asistencia de esta sección en esta materia?
    Tanto administradores como docentes pueden elegir libremente cualquier
    materia y cualquier sección (no depende de 'Permisos de Docentes')."""
    if not current_user.is_authenticated:
        return False
    if not id_seccion or not id_asignatura:
        return False
    return Seccion.query.get(id_seccion) is not None and Asignatura.query.get(id_asignatura) is not None


def puede_gestionar_seccion(id_seccion, campo_permiso):
    """¿El usuario actual tiene el permiso extra (puede_editar / puede_eliminar) en esta sección?"""
    if es_admin():
        return True
    if not id_seccion:
        return False
    filtro = {'id_usuario': current_user.id_usuario, 'id_seccion': id_seccion, campo_permiso: True}
    return AsignacionDocente.query.filter_by(**filtro).first() is not None


CAMPOS_MARCACION = ['entrada_manana', 'salida_manana', 'entrada_tarde', 'salida_tarde']

ETIQUETAS_MARCACION = {
    'entrada_manana': 'Entrada de la mañana',
    'salida_manana': 'Salida de la mañana',
    'entrada_tarde': 'Entrada de la tarde',
    'salida_tarde': 'Salida de la tarde',
}

HORARIOS_POR_DEFECTO = [
    ('entrada_manana', 'Entrada mañana', time_cls(7, 0), time_cls(8, 30)),
    ('salida_manana', 'Salida mañana', time_cls(10, 0), time_cls(11, 59)),
    ('entrada_tarde', 'Entrada tarde', time_cls(12, 0), time_cls(13, 45)),
    ('salida_tarde', 'Salida tarde', time_cls(14, 30), None),
]


def inicializar_datos_por_defecto():
    """Crea tablas nuevas (si no existen) y siembra la configuración de horarios por defecto."""
    db.create_all()
    if ConfiguracionHorario.query.count() == 0:
        for campo, etiqueta, inicio, fin in HORARIOS_POR_DEFECTO:
            db.session.add(ConfiguracionHorario(
                campo=campo, etiqueta=etiqueta, hora_inicio=inicio, hora_fin=fin
            ))
        db.session.commit()
    if Asignatura.query.count() == 0:
        db.session.add(Asignatura(nombre='General'))
        db.session.commit()


def obtener_configuracion_horarios():
    filas = ConfiguracionHorario.query.all()
    return {f.campo: f for f in filas}


def campo_segun_hora_actual(hora_actual):
    """Determina a qué campo de marcación corresponde la hora actual, según las
    ventanas configuradas. Devuelve None si la hora no cae en ninguna ventana."""
    config = obtener_configuracion_horarios()
    for campo in CAMPOS_MARCACION:
        ventana = config.get(campo)
        if not ventana:
            continue
        dentro_inicio = hora_actual >= ventana.hora_inicio
        dentro_fin = ventana.hora_fin is None or hora_actual <= ventana.hora_fin
        if dentro_inicio and dentro_fin:
            return campo
    return None


@app.context_processor
def inyectar_helpers_rol():
    return dict(es_admin=es_admin, es_docente=es_docente)


with app.app_context():
    try:
        inicializar_datos_por_defecto()
    except Exception:
        # La base de datos podría no estar disponible todavía (p. ej. al importar
        # el módulo para pruebas). Las tablas/datos se crean en el primer arranque
        # real contra MySQL.
        pass


# ============================
# Rutas - Login / Logout
# ============================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        nombre_usuario = request.form['nombre_usuario']
        password = request.form['password']

        usuario = Usuario.query.filter_by(nombre_usuario=nombre_usuario).first()

        if usuario and usuario.activo and usuario.check_password(password):
            login_user(usuario)
            siguiente = request.args.get('next')
            return redirect(siguiente or url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ============================
# Rutas - Dashboard
# ============================
@app.route('/')
@login_required
def index():
    if es_docente():
        return redirect(url_for('asistencia'))
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    total_secciones = Seccion.query.count()
    total_responsables = Responsable.query.count()
    total_usuarios = Usuario.query.count()
    total_alumnos = Alumno.query.count()
    return render_template('dashboard.html',
                            total_secciones=total_secciones,
                            total_responsables=total_responsables,
                            total_usuarios=total_usuarios,
                            total_alumnos=total_alumnos)


# ============================
# Rutas CRUD - Secciones
# ============================
@app.route('/secciones')
@login_required
@admin_required
def secciones():
    lista = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()
    return render_template('secciones/index.html', secciones=lista)


@app.route('/secciones/add', methods=['GET', 'POST'])
@login_required
@admin_required
def secciones_add():
    if request.method == 'POST':
        especialidad = request.form['especialidad']
        codigo_seccion = request.form['codigo_seccion']
        grado = request.form['grado']
        nueva = Seccion(especialidad=especialidad, codigo_seccion=codigo_seccion, grado=grado)
        db.session.add(nueva)
        db.session.commit()
        return redirect(url_for('secciones'))
    return render_template('secciones/add.html')


@app.route('/secciones/edit/<int:id_seccion>', methods=['GET', 'POST'])
@login_required
@admin_required
def secciones_edit(id_seccion):
    seccion = Seccion.query.get_or_404(id_seccion)
    if request.method == 'POST':
        seccion.especialidad = request.form['especialidad']
        seccion.codigo_seccion = request.form['codigo_seccion']
        seccion.grado = request.form['grado']
        db.session.commit()
        return redirect(url_for('secciones'))
    return render_template('secciones/edit.html', seccion=seccion)


@app.route('/secciones/delete/<int:id_seccion>')
@login_required
@admin_required
def secciones_delete(id_seccion):
    seccion = Seccion.query.get_or_404(id_seccion)

    tiene_alumnos = Alumno.query.filter_by(id_seccion=id_seccion).count()
    if tiene_alumnos > 0:
        flash(f'No se puede eliminar la sección "{seccion.codigo_seccion}" porque tiene {tiene_alumnos} alumno(s) asignado(s). Reasígnalos primero.', 'danger')
        return redirect(url_for('secciones'))

    db.session.delete(seccion)
    db.session.commit()
    flash('Sección eliminada correctamente.', 'success')
    return redirect(url_for('secciones'))


# ============================
# Rutas CRUD - Responsables
# ============================
@app.route('/responsables')
@login_required
@admin_required
def responsables():
    query = request.args.get('q', '').strip()

    responsables_q = Responsable.query
    if query:
        responsables_q = responsables_q.filter(
            (Responsable.nombre_completo.ilike(f'%{query}%')) | (Responsable.dui.ilike(f'%{query}%'))
        )

    lista = responsables_q.order_by(Responsable.nombre_completo).all()
    return render_template('responsables/index.html', responsables=lista, query=query)

@app.route('/responsables/add', methods=['GET', 'POST'])
@login_required
@admin_required
def responsables_add():
    if request.method == 'POST':
        nombre_completo = request.form['nombre_completo']
        dui = request.form['dui']
        parentesco = request.form['parentesco']
        telefono = request.form['telefono']

        existe = Responsable.query.filter_by(dui=dui).first()
        if existe:
            flash('Ya existe un responsable registrado con ese DUI.', 'danger')
            return render_template('responsables/add.html')

        nuevo = Responsable(nombre_completo=nombre_completo, dui=dui, parentesco=parentesco, telefono=telefono)
        db.session.add(nuevo)
        db.session.commit()
        return redirect(url_for('responsables'))
    return render_template('responsables/add.html')


@app.route('/responsables/edit/<int:id_responsable>', methods=['GET', 'POST'])
@login_required
@admin_required
def responsables_edit(id_responsable):
    responsable = Responsable.query.get_or_404(id_responsable)
    if request.method == 'POST':
        responsable.nombre_completo = request.form['nombre_completo']
        responsable.dui = request.form['dui']
        responsable.parentesco = request.form['parentesco']
        responsable.telefono = request.form['telefono']
        db.session.commit()
        return redirect(url_for('responsables'))
    return render_template('responsables/edit.html', responsable=responsable)

@app.route('/responsables/delete/<int:id_responsable>')
@login_required
@admin_required
def responsables_delete(id_responsable):
    responsable = Responsable.query.get_or_404(id_responsable)
    db.session.delete(responsable)
    db.session.commit()
    return redirect(url_for('responsables'))


# ============================
# Rutas CRUD - Usuarios
# ============================
@app.route('/usuarios')
@login_required
@admin_required
def usuarios():
    lista = Usuario.query.all()
    return render_template('usuarios/index.html', usuarios=lista)


@app.route('/usuarios/add', methods=['GET', 'POST'])
@login_required
@admin_required
def usuarios_add():
    if request.method == 'POST':
        nombre_completo = request.form['nombre_completo']
        correo = request.form['correo']
        nombre_usuario = request.form['nombre_usuario']
        password = request.form['password']
        rol = request.form['rol']

        existe = Usuario.query.filter(
            (Usuario.nombre_usuario == nombre_usuario) | (Usuario.correo == correo)
        ).first()
        if existe:
            flash('Ya existe un usuario con ese nombre de usuario o correo.', 'danger')
            return render_template('usuarios/add.html')

        nuevo = Usuario(
            nombre_completo=nombre_completo,
            correo=correo,
            nombre_usuario=nombre_usuario,
            rol=rol,
            activo=True
        )
        nuevo.set_password(password)
        db.session.add(nuevo)
        db.session.commit()
        flash('Usuario creado correctamente.', 'success')
        return redirect(url_for('usuarios'))

    return render_template('usuarios/add.html')


@app.route('/usuarios/edit/<int:id_usuario>', methods=['GET', 'POST'])
@login_required
@admin_required
def usuarios_edit(id_usuario):
    usuario = Usuario.query.get_or_404(id_usuario)
    if request.method == 'POST':
        usuario.nombre_completo = request.form['nombre_completo']
        usuario.correo = request.form['correo']
        usuario.nombre_usuario = request.form['nombre_usuario']
        usuario.rol = request.form['rol']
        usuario.activo = 'activo' in request.form

        nueva_password = request.form.get('password')
        if nueva_password:
            usuario.set_password(nueva_password)

        db.session.commit()
        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('usuarios'))

    return render_template('usuarios/editar.html', usuario=usuario)


@app.route('/usuarios/delete/<int:id_usuario>')
@login_required
@admin_required
def usuarios_delete(id_usuario):
    if id_usuario == current_user.id_usuario:
        flash('No puedes eliminar tu propio usuario mientras tienes la sesión iniciada.', 'danger')
        return redirect(url_for('usuarios'))

    usuario = Usuario.query.get_or_404(id_usuario)
    db.session.delete(usuario)
    db.session.commit()
    flash('Usuario eliminado.', 'success')
    return redirect(url_for('usuarios'))


# ============================
# Rutas CRUD - Alumnos
# ============================
@app.route('/alumnos')
@login_required
@admin_required
def alumnos():
    id_seccion = request.args.get('id_seccion') or None

    alumnos_q = Alumno.query.join(Seccion, Alumno.id_seccion == Seccion.id_seccion)
    if id_seccion:
        alumnos_q = alumnos_q.filter(Alumno.id_seccion == id_seccion)

    lista = alumnos_q.order_by(Seccion.grado, Seccion.codigo_seccion, Alumno.nombre_completo).all()
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()

    return render_template('alumnos/index.html', alumnos=lista, secciones=secciones, id_seccion=id_seccion or '')


@app.route('/alumnos/add', methods=['GET', 'POST'])
@login_required
@admin_required
def alumnos_add():
    secciones = Seccion.query.all()
    responsables = Responsable.query.all()

    if request.method == 'POST':
        nombre_completo = request.form['nombre_completo']
        nie = request.form['nie']
        genero = request.form['genero']
        id_seccion = request.form['id_seccion']
        id_responsable = request.form.get('id_responsable') or None

        existe = Alumno.query.filter_by(nie=nie).first()
        if existe:
            flash('Ya existe un alumno registrado con ese NIE.', 'danger')
            return render_template('alumnos/add.html', secciones=secciones, responsables=responsables)

        nuevo = Alumno(
            nombre_completo=nombre_completo,
            nie=nie,
            genero=genero,
            id_seccion=id_seccion,
            id_responsable=id_responsable,
            activo=True
        )
        db.session.add(nuevo)
        db.session.commit()
        flash('Alumno registrado correctamente.', 'success')
        return redirect(url_for('alumnos'))

    return render_template('alumnos/add.html', secciones=secciones, responsables=responsables)


@app.route('/alumnos/edit/<int:id_alumno>', methods=['GET', 'POST'])
@login_required
def alumnos_edit(id_alumno):
    alumno = Alumno.query.get_or_404(id_alumno)

    # Un docente solo puede editar datos previos si el administrador le otorgó
    # explícitamente el permiso "puede_editar" en la sección del alumno.
    if not puede_gestionar_seccion(alumno.id_seccion, 'puede_editar'):
        flash('No tienes permiso para editar datos de alumnos. Pide al administrador que te lo asigne.', 'danger')
        return redirect(url_for('asistencia'))

    secciones = Seccion.query.all()
    responsables = Responsable.query.all()

    if request.method == 'POST':
        alumno.nombre_completo = request.form['nombre_completo']
        alumno.nie = request.form['nie']
        alumno.genero = request.form['genero']
        alumno.id_seccion = request.form['id_seccion']
        alumno.id_responsable = request.form.get('id_responsable') or None
        alumno.activo = 'activo' in request.form
        db.session.commit()
        flash('Alumno actualizado correctamente.', 'success')
        if es_docente():
            return redirect(url_for('asistencia'))
        return redirect(url_for('alumnos'))

    return render_template('alumnos/edit.html', alumno=alumno, secciones=secciones, responsables=responsables)


@app.route('/alumnos/delete/<int:id_alumno>')
@login_required
def alumnos_delete(id_alumno):
    alumno = Alumno.query.get_or_404(id_alumno)

    # Un docente solo puede eliminar registros si el administrador le otorgó
    # explícitamente el permiso "puede_eliminar" en la sección del alumno.
    if not puede_gestionar_seccion(alumno.id_seccion, 'puede_eliminar'):
        flash('No tienes permiso para eliminar registros. Pide al administrador que te lo asigne.', 'danger')
        return redirect(url_for('alumnos'))

    # Elimina primero todos los registros de asistencia de este alumno
    Asistencia.query.filter_by(id_alumno=id_alumno).delete()

    db.session.delete(alumno)
    db.session.commit()
    flash('Alumno y su historial de asistencia fueron eliminados.', 'success')

    # Un docente no tiene acceso a la lista general de alumnos (es solo de
    # administrador), así que lo regresamos a su pantalla de asistencia.
    if es_docente():
        return redirect(url_for('asistencia'))
    return redirect(url_for('alumnos'))


# ============================
# Rutas - Registro de Asistencia
# ============================
@app.route('/asistencia')
@login_required
def asistencia():
    fecha_hoy = date.today()
    query = request.args.get('q', '').strip()
    id_seccion_filtro = request.args.get('id_seccion') or None

    alumnos_q = Alumno.query.filter_by(activo=True)

    # Secciones que este usuario puede ver. Para un docente, solo las que el
    # administrador le asignó en "Permisos de Docentes"; esto permite que
    # varios maestros individuales usen la misma pantalla y cada uno vea
    # únicamente sus propios grupos.
    if es_docente():
        secciones_permitidas_ids = secciones_ids_del_docente(current_user.id_usuario)
        if not secciones_permitidas_ids:
            flash('Tu usuario docente todavía no tiene ninguna sección asignada. Contacta al administrador.', 'warning')
        alumnos_q = alumnos_q.filter(Alumno.id_seccion.in_(secciones_permitidas_ids or [-1]))
        secciones_disponibles = Seccion.query.filter(
            Seccion.id_seccion.in_(secciones_permitidas_ids or [-1])
        ).order_by(Seccion.grado, Seccion.codigo_seccion).all()
    else:
        secciones_disponibles = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()

    # Filtro opcional por una sola sección, para que un docente con varios
    # grupos pueda pasar asistencia de uno a la vez si lo prefiere.
    if id_seccion_filtro:
        alumnos_q = alumnos_q.filter(Alumno.id_seccion == id_seccion_filtro)

    if query:
        alumnos_q = alumnos_q.filter(
            (Alumno.nombre_completo.ilike(f'%{query}%')) | (Alumno.nie.ilike(f'%{query}%'))
        )
    lista_alumnos = alumnos_q.join(Seccion, Alumno.id_seccion == Seccion.id_seccion).order_by(
        Seccion.grado, Seccion.codigo_seccion, Alumno.nombre_completo
    ).all()

    registros = {}
    permisos_alumno = {}
    for a in lista_alumnos:
        registros[a.id_alumno] = Asistencia.query.filter_by(id_alumno=a.id_alumno, fecha=fecha_hoy).first()
        permisos_alumno[a.id_alumno] = {
            'puede_editar': puede_gestionar_seccion(a.id_seccion, 'puede_editar'),
            'puede_eliminar': puede_gestionar_seccion(a.id_seccion, 'puede_eliminar'),
        }

    campo_actual = campo_segun_hora_actual(datetime.now().time())
    config_horarios = obtener_configuracion_horarios()

    return render_template('asistencia/index.html',
                            alumnos=lista_alumnos,
                            registros=registros,
                            permisos_alumno=permisos_alumno,
                            secciones_disponibles=secciones_disponibles,
                            id_seccion_filtro=id_seccion_filtro or '',
                            fecha_hoy=fecha_hoy,
                            query=query,
                            campo_actual=campo_actual,
                            etiquetas_marcacion=ETIQUETAS_MARCACION,
                            config_horarios=config_horarios)


@app.route('/asistencia/marcar/<int:id_alumno>', methods=['POST'])
@login_required
def asistencia_marcar(id_alumno):
    alumno = Alumno.query.get_or_404(id_alumno)

    redirect_args = {'q': request.form.get('q', ''), 'id_seccion': request.form.get('id_seccion', '')}

    # Un docente solo puede marcar asistencia de alumnos en sus secciones asignadas.
    if es_docente() and alumno.id_seccion not in secciones_ids_del_docente(current_user.id_usuario):
        flash('No tienes permiso para registrar asistencia de alumnos fuera de tus secciones asignadas.', 'danger')
        return redirect(url_for('asistencia', **redirect_args))

    hoy = date.today()
    ahora = datetime.now()

    # 1. Configuración de Marcaciones y Horarios: la hora actual determina a cuál
    #    de las 4 ventanas (entrada/salida, mañana/tarde) corresponde esta marcación.
    campo = campo_segun_hora_actual(ahora.time())
    if campo is None:
        flash(
            'Fuera de las ventanas de marcación configuradas. Consulta los horarios '
            'de entrada/salida de mañana y tarde con el administrador.',
            'warning'
        )
        return redirect(url_for('asistencia', **redirect_args))

    registro = Asistencia.query.filter_by(id_alumno=id_alumno, fecha=hoy).first()
    if not registro:
        registro = Asistencia(id_alumno=id_alumno, fecha=hoy)
        db.session.add(registro)

    ya_tenia_valor = getattr(registro, campo) is not None
    setattr(registro, campo, ahora)
    db.session.commit()

    etiqueta = ETIQUETAS_MARCACION[campo]
    if ya_tenia_valor:
        # Lógica de Marcación Múltiple: si se presiona varias veces dentro de la
        # misma ventana, solo se conserva el timestamp de la última marcación.
        flash(
            f'{etiqueta} actualizada para {alumno.nombre_completo}: se conservó únicamente '
            f'la última marcación ({ahora.strftime("%H:%M:%S")}).',
            'info'
        )
    else:
        flash(f'{etiqueta} registrada para {alumno.nombre_completo} a las {ahora.strftime("%H:%M:%S")}.', 'success')

    return redirect(url_for('asistencia', **redirect_args))


@app.route('/asistencia/resumen')
@login_required
def asistencia_resumen():
    fecha_hoy = date.today()
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()
    if es_docente():
        permitidas = secciones_ids_del_docente(current_user.id_usuario)
        secciones = [s for s in secciones if s.id_seccion in permitidas]

    resumen = []
    datos_modal = {}  # {id_seccion: {campo: [nombres de alumnos]}}

    for s in secciones:
        alumnos_seccion = Alumno.query.filter_by(id_seccion=s.id_seccion, activo=True).order_by(Alumno.nombre_completo).all()
        total = len(alumnos_seccion)
        masculinos = sum(1 for a in alumnos_seccion if a.genero == 'M')
        femeninos = sum(1 for a in alumnos_seccion if a.genero == 'F')

        ids_alumnos = [a.id_alumno for a in alumnos_seccion]
        registros_hoy = {}
        if ids_alumnos:
            filas = Asistencia.query.filter(
                Asistencia.id_alumno.in_(ids_alumnos),
                Asistencia.fecha == fecha_hoy
            ).all()
            registros_hoy = {f.id_alumno: f for f in filas}

        # Cuenta y lista de nombres por cada una de las 4 marcaciones del día.
        metricas = {campo: {'total': 0, 'alumnos': []} for campo in CAMPOS_MARCACION}
        for a in alumnos_seccion:
            reg = registros_hoy.get(a.id_alumno)
            for campo in CAMPOS_MARCACION:
                if reg is not None and getattr(reg, campo) is not None:
                    metricas[campo]['total'] += 1
                    metricas[campo]['alumnos'].append(a.nombre_completo)

        for campo in CAMPOS_MARCACION:
            metricas[campo]['porcentaje'] = round((metricas[campo]['total'] / total) * 100) if total > 0 else 0

        entraron = metricas['entrada_manana']['total']
        no_entraron = total - entraron

        resumen.append({
            'seccion': s,
            'total': total,
            'masculinos': masculinos,
            'femeninos': femeninos,
            'entraron': entraron,
            'no_entraron': no_entraron,
            'metricas': metricas,
        })

        datos_modal[s.id_seccion] = {campo: metricas[campo]['alumnos'] for campo in CAMPOS_MARCACION}

    return render_template('asistencia/resumen.html',
                            resumen=resumen,
                            fecha_hoy=fecha_hoy,
                            etiquetas_marcacion=ETIQUETAS_MARCACION,
                            datos_modal=datos_modal)


# ============================
# Rutas - Asistencia por Materia (Presente / Ausente / Tardanza)
# ============================
def construir_materias_y_mapa(pares_seccion_asignatura):
    """A partir de una lista de pares (seccion, asignatura) construye:
    - materias: lista ordenada de materias únicas [{'id':..,'nombre':..}]
    - mapa: {id_asignatura: [{'id':id_seccion, 'label':'1A - General (Grado 1)'}, ...]}
    Esto permite que el formulario de selección primero pida la materia y luego,
    con JavaScript (sin recargar la página), filtre solo las secciones donde el
    docente da esa materia."""
    materias_por_id = {}
    mapa = {}
    for seccion, asignatura in pares_seccion_asignatura:
        materias_por_id[asignatura.id_asignatura] = asignatura.nombre
        etiqueta_seccion = f"{seccion.codigo_seccion} - {seccion.especialidad} (Grado {seccion.grado})"
        mapa.setdefault(asignatura.id_asignatura, [])
        if not any(s['id'] == seccion.id_seccion for s in mapa[asignatura.id_asignatura]):
            mapa[asignatura.id_asignatura].append({'id': seccion.id_seccion, 'label': etiqueta_seccion})

    materias = [
        {'id': id_asig, 'nombre': nombre}
        for id_asig, nombre in sorted(materias_por_id.items(), key=lambda x: x[1])
    ]
    return materias, mapa


@app.route('/asistencia/materia')
@login_required
def asistencia_materia_seleccionar():
    """Pantalla donde CUALQUIER usuario (docente o admin) elige primero la
    Materia que está dando en ese momento, y luego la Sección a la que le va
    a pasar asistencia. No depende de 'Permisos de Docentes': cualquier
    docente puede elegir cualquier materia y cualquier sección."""
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()
    asignaturas_lista = Asignatura.query.order_by(Asignatura.nombre).all()

    if not secciones or not asignaturas_lista:
        flash('Todavía no hay secciones o materias registradas en el sistema.', 'warning')

    pares = [(s, a) for a in asignaturas_lista for s in secciones]
    materias, mapa = construir_materias_y_mapa(pares)

    return render_template('asistencia/materia_seleccionar.html', materias=materias, mapa_materia_secciones=mapa)


@app.route('/asistencia/materia/tomar')
@login_required
def asistencia_materia_tomar():
    id_seccion = request.args.get('id_seccion', type=int)
    id_asignatura = request.args.get('id_asignatura', type=int)
    fecha_str = request.args.get('fecha', '').strip()

    if not id_seccion or not id_asignatura:
        flash('Selecciona una sección y una materia para pasar asistencia.', 'warning')
        return redirect(url_for('asistencia_materia_seleccionar'))

    if not puede_tomar_asistencia_materia(id_seccion, id_asignatura):
        flash('No tienes permiso para pasar asistencia en esa sección/materia.', 'danger')
        return redirect(url_for('asistencia_materia_seleccionar'))

    seccion = Seccion.query.get_or_404(id_seccion)
    asignatura = Asignatura.query.get_or_404(id_asignatura)

    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Fecha inválida.', 'danger')
            fecha = date.today()
    else:
        fecha = date.today()

    if fecha > date.today():
        flash('No puedes pasar asistencia de una fecha futura.', 'warning')
        fecha = date.today()

    alumnos_lista = Alumno.query.filter_by(id_seccion=id_seccion, activo=True).order_by(Alumno.nombre_completo).all()

    registros = {
        r.id_alumno: r.estado
        for r in AsistenciaMateria.query.filter_by(id_asignatura=id_asignatura, fecha=fecha)
        .filter(AsistenciaMateria.id_alumno.in_([a.id_alumno for a in alumnos_lista] or [-1]))
        .all()
    }

    return render_template(
        'asistencia/materia_tomar.html',
        seccion=seccion,
        asignatura=asignatura,
        fecha=fecha,
        fecha_hoy=date.today(),
        alumnos=alumnos_lista,
        registros=registros,
        estados=ESTADOS_ASISTENCIA_MATERIA,
    )


@app.route('/asistencia/materia/guardar', methods=['POST'])
@login_required
def asistencia_materia_guardar():
    id_seccion = request.form.get('id_seccion', type=int)
    id_asignatura = request.form.get('id_asignatura', type=int)
    fecha_str = request.form.get('fecha', '').strip()

    redirect_args = {'id_seccion': id_seccion, 'id_asignatura': id_asignatura, 'fecha': fecha_str}

    if not id_seccion or not id_asignatura:
        flash('Selecciona una sección y una materia para pasar asistencia.', 'warning')
        return redirect(url_for('asistencia_materia_seleccionar'))

    if not puede_tomar_asistencia_materia(id_seccion, id_asignatura):
        flash('No tienes permiso para pasar asistencia en esa sección/materia.', 'danger')
        return redirect(url_for('asistencia_materia_seleccionar'))

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Fecha inválida.', 'danger')
        return redirect(url_for('asistencia_materia_seleccionar'))

    if fecha > date.today():
        flash('No puedes pasar asistencia de una fecha futura.', 'warning')
        return redirect(url_for('asistencia_materia_tomar', **redirect_args))

    alumnos_lista = Alumno.query.filter_by(id_seccion=id_seccion, activo=True).all()
    ahora = datetime.now()

    for a in alumnos_lista:
        estado = request.form.get(f'estado_{a.id_alumno}')
        if estado not in ESTADOS_ASISTENCIA_MATERIA:
            continue

        registro = AsistenciaMateria.query.filter_by(
            id_alumno=a.id_alumno, id_asignatura=id_asignatura, fecha=fecha
        ).first()

        if registro:
            registro.estado = estado
            registro.id_docente = current_user.id_usuario
            registro.id_seccion = id_seccion
            registro.registrado_en = ahora
        else:
            db.session.add(AsistenciaMateria(
                id_alumno=a.id_alumno,
                id_seccion=id_seccion,
                id_asignatura=id_asignatura,
                id_docente=current_user.id_usuario,
                fecha=fecha,
                estado=estado,
                registrado_en=ahora,
            ))

    db.session.commit()
    flash('Asistencia de la materia guardada correctamente.', 'success')
    return redirect(url_for('asistencia_materia_tomar', **redirect_args))


@app.route('/asistencia/materia/escanear')
@login_required
def asistencia_materia_escanear():
    """Pantalla con la cámara para escanear el QR del carnet de cada alumno."""
    id_seccion = request.args.get('id_seccion', type=int)
    id_asignatura = request.args.get('id_asignatura', type=int)
    fecha_str = request.args.get('fecha', '').strip()

    if not id_seccion or not id_asignatura:
        flash('Selecciona una sección y una materia para pasar asistencia.', 'warning')
        return redirect(url_for('asistencia_materia_seleccionar'))

    if not puede_tomar_asistencia_materia(id_seccion, id_asignatura):
        flash('No tienes permiso para pasar asistencia en esa sección/materia.', 'danger')
        return redirect(url_for('asistencia_materia_seleccionar'))

    seccion = Seccion.query.get_or_404(id_seccion)
    asignatura = Asignatura.query.get_or_404(id_asignatura)

    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = date.today()
    else:
        fecha = date.today()

    total_alumnos = Alumno.query.filter_by(id_seccion=id_seccion, activo=True).count()
    ya_registrados = AsistenciaMateria.query.filter_by(
        id_seccion=id_seccion, id_asignatura=id_asignatura, fecha=fecha
    ).count()

    return render_template(
        'asistencia/materia_escanear.html',
        seccion=seccion,
        asignatura=asignatura,
        fecha=fecha,
        total_alumnos=total_alumnos,
        ya_registrados=ya_registrados,
    )


@app.route('/asistencia/materia/marcar_qr', methods=['POST'])
@login_required
def asistencia_materia_marcar_qr():
    """Recibe el contenido leído del QR del carnet y marca al alumno como
    presente en la materia/sección/fecha indicadas. Responde en JSON porque
    lo consume la pantalla de escaneo vía JavaScript (sin recargar la página)."""
    datos = request.get_json(silent=True) or {}
    id_seccion = datos.get('id_seccion')
    id_asignatura = datos.get('id_asignatura')
    fecha_str = datos.get('fecha', '')
    qr_contenido = datos.get('qr_contenido', '')

    try:
        id_seccion = int(id_seccion)
        id_asignatura = int(id_asignatura)
    except (TypeError, ValueError):
        return jsonify(ok=False, mensaje='Sección o materia inválida.'), 400

    if not puede_tomar_asistencia_materia(id_seccion, id_asignatura):
        return jsonify(ok=False, mensaje='No tienes permiso para pasar asistencia aquí.'), 403

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify(ok=False, mensaje='Fecha inválida.'), 400

    if fecha > date.today():
        return jsonify(ok=False, mensaje='No puedes pasar asistencia de una fecha futura.'), 400

    # El QR del carnet trae un JSON con el NIE y el nombre del alumno
    # (el nombre es solo referencia visual; lo único que se usa para
    # identificar al alumno de verdad es el NIE, que es único en el sistema).
    nie = None
    if qr_contenido:
        try:
            datos_qr = json.loads(qr_contenido)
            nie = str(datos_qr.get('nie', '')).strip()
        except (ValueError, TypeError):
            nie = qr_contenido.strip()

    if not nie:
        return jsonify(ok=False, mensaje='El código QR no contiene un NIE válido.'), 400

    alumno = Alumno.query.filter_by(nie=nie, activo=True).first()
    if not alumno:
        return jsonify(ok=False, mensaje=f'No se encontró ningún alumno activo con NIE {nie}.'), 404

    if alumno.id_seccion != id_seccion:
        return jsonify(
            ok=False,
            mensaje=f'{alumno.nombre_completo} no pertenece a esta sección.'
        ), 409

    registro = AsistenciaMateria.query.filter_by(
        id_alumno=alumno.id_alumno, id_asignatura=id_asignatura, fecha=fecha
    ).first()

    ya_estaba_presente = registro is not None and registro.estado == 'presente'

    if registro:
        registro.estado = 'presente'
        registro.id_docente = current_user.id_usuario
        registro.id_seccion = id_seccion
        registro.registrado_en = datetime.now()
    else:
        db.session.add(AsistenciaMateria(
            id_alumno=alumno.id_alumno,
            id_seccion=id_seccion,
            id_asignatura=id_asignatura,
            id_docente=current_user.id_usuario,
            fecha=fecha,
            estado='presente',
            registrado_en=datetime.now(),
        ))
    db.session.commit()

    return jsonify(
        ok=True,
        id_alumno=alumno.id_alumno,
        nombre=alumno.nombre_completo,
        nie=alumno.nie,
        repetido=ya_estaba_presente,
    )


# ============================
# Rutas CRUD - Carnets con QR (Administrador)
# ============================
@app.route('/alumnos/carnets')
@login_required
@admin_required
def alumnos_carnets():
    """Página imprimible con el carnet (incluye QR) de cada alumno de una sección."""
    id_seccion = request.args.get('id_seccion', type=int)
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()

    alumnos_lista = []
    seccion_seleccionada = None
    if id_seccion:
        seccion_seleccionada = Seccion.query.get_or_404(id_seccion)
        alumnos_lista = Alumno.query.filter_by(id_seccion=id_seccion, activo=True).order_by(Alumno.nombre_completo).all()

    return render_template(
        'alumnos/carnets.html',
        secciones=secciones,
        id_seccion=id_seccion or '',
        seccion=seccion_seleccionada,
        alumnos=alumnos_lista,
    )


# ============================
# Rutas - Reportes
# ============================
def _calcular_reporte(id_seccion, fecha_inicio, fecha_fin):
    """Arma la lista de filas del reporte: un alumno por fila con su % de asistencia."""
    alumnos_q = Alumno.query.filter_by(activo=True)
    if id_seccion:
        alumnos_q = alumnos_q.filter_by(id_seccion=id_seccion)
    lista_alumnos = alumnos_q.order_by(Alumno.nombre_completo).all()

    total_dias = (fecha_fin - fecha_inicio).days + 1
    if total_dias < 1:
        total_dias = 1

    filas = []
    for a in lista_alumnos:
        registros = Asistencia.query.filter(
            Asistencia.id_alumno == a.id_alumno,
            Asistencia.fecha >= fecha_inicio,
            Asistencia.fecha <= fecha_fin
        ).all()
        dias_asistidos = sum(1 for r in registros if r.entrada_manana is not None)
        porcentaje = round((dias_asistidos / total_dias) * 100, 1)
        filas.append({
            'alumno': a,
            'dias_asistidos': dias_asistidos,
            'total_dias': total_dias,
            'porcentaje': porcentaje
        })
    return filas
def _calcular_reporte_individual(alumno, fecha_inicio, fecha_fin):
    """Detalle día a día de asistencia de un alumno en un rango de fechas."""
    registros = Asistencia.query.filter(
        Asistencia.id_alumno == alumno.id_alumno,
        Asistencia.fecha >= fecha_inicio,
        Asistencia.fecha <= fecha_fin
    ).order_by(Asistencia.fecha).all()

    total_dias = (fecha_fin - fecha_inicio).days + 1
    if total_dias < 1:
        total_dias = 1

    dias_asistidos = sum(1 for r in registros if r.entrada_manana is not None)
    porcentaje = round((dias_asistidos / total_dias) * 100, 1)

    return {
        'registros': registros,
        'dias_asistidos': dias_asistidos,
        'total_dias': total_dias,
        'porcentaje': porcentaje
    }


@app.route('/alumnos/buscar')
@login_required
def alumnos_buscar():
    """Endpoint JSON para el buscador de alumnos (nombre, apellido o NIE)."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    like = f"%{q}%"
    resultados = Alumno.query.filter(
        Alumno.activo == True,
        db.or_(
            Alumno.nombre_completo.ilike(like),
            Alumno.nie.ilike(like)
        )
    ).order_by(Alumno.nombre_completo).limit(10).all()

    return jsonify([
        {
            'id_alumno': a.id_alumno,
            'nombre_completo': a.nombre_completo,
            'nie': a.nie,
            'seccion': a.seccion.codigo_seccion if a.seccion else 'Sin sección'
        }
        for a in resultados
    ])

def _leer_filtros_reporte():
    """Lee y valida id_seccion / fecha_inicio / fecha_fin desde la URL (?query=...)."""
    id_seccion = request.args.get('id_seccion') or None
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')

    fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
    fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()

    if fecha_inicio > fecha_fin:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

    return id_seccion, fecha_inicio, fecha_fin


@app.route('/reportes')
@login_required
def reportes():
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()
    if es_docente():
        permitidas = {
            a.id_seccion for a in AsignacionDocente.query.filter_by(
                id_usuario=current_user.id_usuario, puede_reportes=True
            ).all()
        }
        secciones = [s for s in secciones if s.id_seccion in permitidas]
        if not secciones:
            flash('No tienes permiso de generar reportes. Pide al administrador que te lo asigne.', 'warning')
    hoy = date.today().isoformat()
    return render_template('reportes/index.html', secciones=secciones, hoy=hoy, mostrar_todas=es_admin())


@app.route('/reportes/generar')
@login_required
def reportes_generar():
    try:
        id_seccion, fecha_inicio, fecha_fin = _leer_filtros_reporte()
    except (ValueError, TypeError):
        flash('Debes seleccionar un rango de fechas válido.', 'danger')
        return redirect(url_for('reportes'))

    if not puede_ver_reportes_seccion(id_seccion):
        flash('No tienes permiso para generar el reporte de esa sección.', 'danger')
        return redirect(url_for('reportes'))

    seccion_obj = Seccion.query.get(id_seccion) if id_seccion else None
    filas = _calcular_reporte(id_seccion, fecha_inicio, fecha_fin)

    return render_template(
        'reportes/resultado.html',
        filas=filas,
        seccion=seccion_obj,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_seccion=id_seccion or ''
    )


@app.route('/reportes/exportar_csv')
@login_required
def reportes_exportar_csv():
    try:
        id_seccion, fecha_inicio, fecha_fin = _leer_filtros_reporte()
    except (ValueError, TypeError):
        flash('Debes seleccionar un rango de fechas válido.', 'danger')
        return redirect(url_for('reportes'))

    if not puede_ver_reportes_seccion(id_seccion):
        flash('No tienes permiso para exportar el reporte de esa sección.', 'danger')
        return redirect(url_for('reportes'))

    seccion_obj = Seccion.query.get(id_seccion) if id_seccion else None
    filas = _calcular_reporte(id_seccion, fecha_inicio, fecha_fin)

    salida = io.StringIO()
    writer = csv.writer(salida)
    writer.writerow(['Alumno', 'NIE', 'Sección', 'Días asistidos', 'Días del período', 'Porcentaje de asistencia'])
    for f in filas:
        writer.writerow([
            f['alumno'].nombre_completo,
            f['alumno'].nie,
            f['alumno'].seccion.codigo_seccion if f['alumno'].seccion else '',
            f['dias_asistidos'],
            f['total_dias'],
            f"{f['porcentaje']}%"
        ])

    nombre_archivo = f"reporte_asistencia_{fecha_inicio}_{fecha_fin}.csv"
    return Response(
        salida.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={nombre_archivo}'}
    )

@app.route('/reportes/alumno/<int:id_alumno>')
@login_required
def reportes_generar_alumno(id_alumno):
    alumno = Alumno.query.get_or_404(id_alumno)

    if not puede_ver_reportes_seccion(alumno.id_seccion):
        flash('No tienes permiso para generar el reporte de este alumno.', 'danger')
        return redirect(url_for('reportes'))

    try:
        _, fecha_inicio, fecha_fin = _leer_filtros_reporte()
    except (ValueError, TypeError):
        flash('Debes seleccionar un rango de fechas válido.', 'danger')
        return redirect(url_for('reportes'))

    datos = _calcular_reporte_individual(alumno, fecha_inicio, fecha_fin)

    return render_template(
        'reportes/alumno.html',
        alumno=alumno,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        **datos
    )

# ============================
# Rutas CRUD - Asignaturas (Administrador)
# ============================
@app.route('/asignaturas')
@login_required
@admin_required
def asignaturas():
    lista = Asignatura.query.order_by(Asignatura.nombre).all()
    return render_template('asignaturas/index.html', asignaturas=lista)


@app.route('/asignaturas/add', methods=['GET', 'POST'])
@login_required
@admin_required
def asignaturas_add():
    if request.method == 'POST':
        nombre = request.form['nombre'].strip()
        if Asignatura.query.filter_by(nombre=nombre).first():
            flash('Ya existe una asignatura con ese nombre.', 'danger')
            return render_template('asignaturas/add.html')
        db.session.add(Asignatura(nombre=nombre))
        db.session.commit()
        flash('Asignatura creada correctamente.', 'success')
        return redirect(url_for('asignaturas'))
    return render_template('asignaturas/add.html')


@app.route('/asignaturas/edit/<int:id_asignatura>', methods=['GET', 'POST'])
@login_required
@admin_required
def asignaturas_edit(id_asignatura):
    asignatura = Asignatura.query.get_or_404(id_asignatura)
    if request.method == 'POST':
        asignatura.nombre = request.form['nombre'].strip()
        db.session.commit()
        flash('Asignatura actualizada correctamente.', 'success')
        return redirect(url_for('asignaturas'))
    return render_template('asignaturas/edit.html', asignatura=asignatura)


@app.route('/asignaturas/delete/<int:id_asignatura>')
@login_required
@admin_required
def asignaturas_delete(id_asignatura):
    asignatura = Asignatura.query.get_or_404(id_asignatura)
    en_uso = AsignacionDocente.query.filter_by(id_asignatura=id_asignatura).count()
    if en_uso > 0:
        flash('No se puede eliminar: hay asignaciones de docentes que usan esta asignatura.', 'danger')
        return redirect(url_for('asignaturas'))
    db.session.delete(asignatura)
    db.session.commit()
    flash('Asignatura eliminada correctamente.', 'success')
    return redirect(url_for('asignaturas'))


# ============================
# Rutas - Permisos Granulares de Docentes (Administrador)
# ============================
@app.route('/asignaciones')
@login_required
@admin_required
def asignaciones():
    lista = AsignacionDocente.query.join(Usuario).order_by(Usuario.nombre_completo).all()
    return render_template('asignaciones/index.html', asignaciones=lista)


@app.route('/asignaciones/add', methods=['GET', 'POST'])
@login_required
@admin_required
def asignaciones_add():
    docentes = Usuario.query.filter_by(rol='docente').order_by(Usuario.nombre_completo).all()
    secciones = Seccion.query.order_by(Seccion.grado, Seccion.codigo_seccion).all()
    asignaturas_lista = Asignatura.query.order_by(Asignatura.nombre).all()

    if request.method == 'POST':
        id_usuario = request.form['id_usuario']
        id_seccion = request.form['id_seccion']
        id_asignatura = request.form['id_asignatura']

        existe = AsignacionDocente.query.filter_by(
            id_usuario=id_usuario, id_seccion=id_seccion, id_asignatura=id_asignatura
        ).first()
        if existe:
            flash('Ese docente ya tiene una asignación para esa sección y asignatura. Edítala en vez de duplicarla.', 'danger')
            return render_template('asignaciones/add.html', docentes=docentes, secciones=secciones, asignaturas=asignaturas_lista)

        nueva = AsignacionDocente(
            id_usuario=id_usuario,
            id_seccion=id_seccion,
            id_asignatura=id_asignatura,
            puede_reportes='puede_reportes' in request.form,
            puede_editar='puede_editar' in request.form,
            puede_eliminar='puede_eliminar' in request.form,
        )
        db.session.add(nueva)
        db.session.commit()
        flash('Asignación creada correctamente. El docente ya puede pasar asistencia en esa sección.', 'success')
        return redirect(url_for('asignaciones'))

    return render_template('asignaciones/add.html', docentes=docentes, secciones=secciones, asignaturas=asignaturas_lista)


@app.route('/asignaciones/edit/<int:id_asignacion>', methods=['GET', 'POST'])
@login_required
@admin_required
def asignaciones_edit(id_asignacion):
    asignacion = AsignacionDocente.query.get_or_404(id_asignacion)
    if request.method == 'POST':
        asignacion.puede_reportes = 'puede_reportes' in request.form
        asignacion.puede_editar = 'puede_editar' in request.form
        asignacion.puede_eliminar = 'puede_eliminar' in request.form
        db.session.commit()
        flash('Permisos actualizados correctamente.', 'success')
        return redirect(url_for('asignaciones'))
    return render_template('asignaciones/edit.html', asignacion=asignacion)


@app.route('/asignaciones/delete/<int:id_asignacion>')
@login_required
@admin_required
def asignaciones_delete(id_asignacion):
    asignacion = AsignacionDocente.query.get_or_404(id_asignacion)
    db.session.delete(asignacion)
    db.session.commit()
    flash('Asignación eliminada correctamente.', 'success')
    return redirect(url_for('asignaciones'))


# ============================
# Rutas - Configuración de Horarios (Administrador)
# ============================
@app.route('/configuracion/horarios', methods=['GET', 'POST'])
@login_required
@admin_required
def configuracion_horarios():
    config = obtener_configuracion_horarios()

    if request.method == 'POST':
        for campo in CAMPOS_MARCACION:
            ventana = config.get(campo)
            if not ventana:
                continue
            inicio_str = request.form.get(f'{campo}_inicio')
            fin_str = request.form.get(f'{campo}_fin')

            try:
                ventana.hora_inicio = datetime.strptime(inicio_str, '%H:%M').time()
            except (ValueError, TypeError):
                flash(f'Hora de inicio inválida para {ventana.etiqueta}.', 'danger')
                return redirect(url_for('configuracion_horarios'))

            if fin_str:
                try:
                    ventana.hora_fin = datetime.strptime(fin_str, '%H:%M').time()
                except ValueError:
                    flash(f'Hora de fin inválida para {ventana.etiqueta}.', 'danger')
                    return redirect(url_for('configuracion_horarios'))
            else:
                ventana.hora_fin = None  # "en adelante"

        db.session.commit()
        flash('Configuración de horarios actualizada correctamente.', 'success')
        return redirect(url_for('configuracion_horarios'))

    ventanas_ordenadas = [config[c] for c in CAMPOS_MARCACION if c in config]
    return render_template('configuracion/horarios.html', ventanas=ventanas_ordenadas)


if __name__ == '__main__':
    app.run(debug=True)