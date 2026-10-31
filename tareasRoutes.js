// Importa la librería Express
const express = require('express');
// Crea un nuevo enrutador de Express para gestionar las rutas de manera modular
const router = express.Router();
// Importa el controlador que contiene la lógica para manejar las peticiones de las tareas
const tareasController = require('../controllers/tareasControllers');

// Define la ruta para el método POST en el endpoint "/tareas". Cuando se recibe esta petición, se ejecuta la función registrarTarea del controlador
router.post('/tareas', tareasController.registrarTarea);

// Define la ruta para el método GET en el endpoint "/tareas". Cuando se recibe esta petición, se ejecuta la función obtenerTareas del controlador
router.get('/tareas', tareasController.obtenerTareas);

// Define la ruta para el método PUT en el endpoint "/tareas/:id". Cuando se recibe esta petición, se ejecuta la función actualizarEstado del controlador
router.put('/tareas/:id', tareasController.actualizarEstado);

// Exporta el enrutador configurado para que pueda ser utilizado en el archivo principal (app.js)
module.exports = router;