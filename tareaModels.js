// Importa el módulo que maneja la lectura y escritura directa en el archivo de texto
const archivo = require('../config/Archivo');

// Define la clase Nodo: cada nodo guarda una tarea y una referencia al siguiente nodo de la lista
class Nodo {
    constructor(tarea) {
        // Guarda el objeto de la tarea (id, nombre, descripcion y estado)
        this.tarea = tarea;
        // Referencia al siguiente nodo; es null mientras este sea el último de la lista
        this.siguiente = null;
    }
}

// Define la clase ListaEnlazada: una cadena de nodos donde cada uno apunta al siguiente
class ListaEnlazada {
    constructor() {
        // La cabeza es el primer nodo de la lista; es null cuando la lista está vacía
        this.cabeza = null;
        // Lleva la cuenta de cuántos nodos tiene la lista
        this.tamano = 0;
    }

    // Agrega una tarea al final de la lista
    agregar(tarea) {
        // Crea un nodo nuevo con la tarea recibida
        const nuevo = new Nodo(tarea);

        // Si la lista está vacía, el nuevo nodo se convierte en la cabeza
        if (this.cabeza === null) {
            this.cabeza = nuevo;
        } else {
            // Si no está vacía, recorre los nodos hasta llegar al último (el que no tiene siguiente)
            let actual = this.cabeza;
            while (actual.siguiente !== null) {
                actual = actual.siguiente;
            }
            // Enlaza el último nodo con el nuevo
            actual.siguiente = nuevo;
        }

        // Aumenta el contador de nodos
        this.tamano++;
    }

    // Busca una tarea por su ID recorriendo la lista nodo por nodo
    buscarPorId(id) {
        // Empieza en la cabeza de la lista
        let actual = this.cabeza;
        // Avanza mientras todavía haya nodos por revisar
        while (actual !== null) {
            // Si el ID de la tarea del nodo coincide con el buscado, retorna esa tarea
            if (actual.tarea.id === Number(id)) {
                return actual.tarea;
            }
            // Pasa al siguiente nodo
            actual = actual.siguiente;
        }
        // Si recorrió toda la lista sin encontrarla, retorna un valor nulo
        return null;
    }

    // Recorre la lista completa y devuelve todas las tareas en un arreglo (en el mismo orden de la lista)
    aArreglo() {
        // Arreglo donde se irán guardando las tareas
        const resultado = [];
        // Empieza en la cabeza de la lista
        let actual = this.cabeza;
        // Avanza nodo por nodo hasta llegar al final
        while (actual !== null) {
            // Agrega la tarea del nodo actual al resultado
            resultado.push(actual.tarea);
            // Pasa al siguiente nodo
            actual = actual.siguiente;
        }
        // Retorna el arreglo con todas las tareas
        return resultado;
    }
}

// Inicializa la lista enlazada en memoria para almacenar las tareas en ejecución
let tareas = new ListaEnlazada();
// Inicializa un contador numérico para generar identificadores únicos para cada nueva tarea
let siguienteId = 1;

// Define la función para cargar las tareas existentes desde el archivo de texto al iniciar la aplicación
function cargarTareas() {
    // Obtiene un arreglo de strings, donde cada string representa una línea del archivo de texto
    const lineas = archivo.leerLineas();
    // Crea una lista enlazada vacía para llenarla con las tareas del archivo
    tareas = new ListaEnlazada();
    // Lleva el ID más alto encontrado en el archivo
    let maxId = 0;

    // Recorre cada línea del archivo para convertirla en una tarea y agregarla a la lista
    lineas.forEach(linea => {
        // Separa los valores de la línea por el carácter "|"
        const [id, nombre, descripcion, estado] = linea.split('|');
        // Agrega un nodo a la lista con la tarea estructurada y el ID convertido a tipo numérico
        tareas.agregar({
            id: Number(id),
            nombre,
            descripcion,
            estado
        });
        // Actualiza el ID más alto si este es mayor
        if (Number(id) > maxId) {
            maxId = Number(id);
        }
    });

    // Si existen tareas cargadas, establece el siguiente ID como el máximo más uno
    if (tareas.tamano > 0) {
        siguienteId = maxId + 1;
    }
}

// Define la función para guardar el estado actual de la lista enlazada en el archivo de texto
function guardarTareas() {
    // Recorre la lista y convierte cada tarea en un string, uniendo sus propiedades con el carácter "|"
    const lineas = tareas.aArreglo().map(t => `${t.id}|${t.nombre}|${t.descripcion}|${t.estado}`);
    // Escribe el arreglo de strings en el archivo, uniendo cada elemento con un salto de línea
    archivo.escribirLineas(lineas);
}

// Función asíncrona para registrar y persistir una nueva tarea
async function registrarTarea(nombre, descripcion, estado) {
    // Crea un objeto para la nueva tarea asignándole el ID actual y uniendo sus atributos
    const tarea = {
        id: siguienteId++,
        nombre,
        descripcion,
        estado
    };

    // Agrega la nueva tarea como un nodo al final de la lista enlazada
    tareas.agregar(tarea);
    // Llama a la función para guardar la lista actualizada en el archivo de texto
    guardarTareas();

    // Retorna el objeto de la tarea recién creada
    return tarea;
}

// Función asíncrona para buscar una tarea específica dentro de la lista enlazada utilizando su ID
async function obtenerTarea(id) {
    // Recorre la lista buscando la tarea cuyo ID coincida; si no se encuentra, retorna un valor nulo
    return tareas.buscarPorId(id);
}

// Función asíncrona para obtener la lista completa de todas las tareas registradas
async function obtenerTodasLasTareas() {
    // Recorre la lista enlazada y retorna todas las tareas en un arreglo
    return tareas.aArreglo();
}

// Función asíncrona para cambiar el estado de una tarea existente y persistir el cambio
async function actualizarEstado(id, estado) {
    // Busca la tarea por su ID dentro de la lista enlazada
    const tarea = tareas.buscarPorId(id);
    // Si no existe ninguna tarea con ese ID, retorna un valor nulo
    if (!tarea) {
        return null;
    }
    // Actualiza el estado de la tarea encontrada
    tarea.estado = estado;
    // Guarda la lista actualizada en el archivo de texto
    guardarTareas();
    // Retorna la tarea con su nuevo estado
    return tarea;
}

// Ejecuta la función cargarTareas de forma automática al importar o cargar el módulo por primera vez
cargarTareas();

// Exporta las funciones para que puedan ser utilizadas en el controlador
module.exports = {
    registrarTarea,
    obtenerTarea,
    obtenerTodasLasTareas,
    actualizarEstado
};
