<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IncubaTrack PRO | Gestión de Lotes</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        .status-critico { @apply bg-red-100 text-red-800 border-l-4 border-red-600; }
        .status-riesgo { @apply bg-yellow-100 text-yellow-800 border-l-4 border-yellow-500; }
        .status-optimo { @apply bg-green-100 text-green-800 border-l-4 border-green-500; }
    </style>
</head>
<body class="bg-slate-50 text-slate-900 font-sans">

    <header class="bg-blue-900 text-white p-4 shadow-lg">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl font-bold flex items-center gap-2">
                <i data-lucide="egg"></i> IncubaTrack PRO
            </h1>
            <div id="reloj" class="text-sm font-mono opacity-80"></div>
        </div>
    </header>

    <main class="container mx-auto p-6">
        
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
                <p class="text-xs text-slate-500 uppercase font-bold">Total Huevos</p>
                <h2 id="dash-huevos" class="text-3xl font-black text-blue-600">0</h2>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
                <p class="text-xs text-slate-500 uppercase font-bold">Lotes Activos</p>
                <h2 id="dash-lotes" class="text-3xl font-black text-blue-600">0</h2>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
                <p class="text-xs text-slate-500 uppercase font-bold">En Riesgo (>7d)</p>
                <h2 id="dash-riesgo" class="text-3xl font-black text-orange-500">0</h2>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
                <p class="text-xs text-slate-500 uppercase font-bold">Críticos (>10d)</p>
                <h2 id="dash-critico" class="text-3xl font-black text-red-600">0</h2>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            
            <section class="lg:col-span-1">
                <div class="bg-white p-6 rounded-2xl shadow-md border border-slate-200">
                    <h3 class="text-lg font-bold mb-4 flex items-center gap-2 text-green-700">
                        <i data-lucide="log-in"></i> Recepción de Huevos
                    </h3>
                    <form id="form-recepcion" class="space-y-3">
                        <div class="grid grid-cols-2 gap-2">
                            <input type="text" id="lote" placeholder="Lote ID" class="w-full p-2 border rounded-md" required>
                            <input type="text" id="granja" placeholder="Granja" class="w-full p-2 border rounded-md" required>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <select id="genetica" class="w-full p-2 border rounded-md">
                                <option value="Cobb 500">Cobb 500</option>
                                <option value="Ross 308">Ross 308</option>
                                <option value="Hubbard">Hubbard</option>
                            </select>
                            <input type="number" id="edadRepro" placeholder="Edad Repro (Sem)" class="w-full p-2 border rounded-md">
                        </div>
                        <div class="space-y-1">
                            <label class="text-xs font-semibold">Fecha Postura / Llegada</label>
                            <div class="grid grid-cols-2 gap-2">
                                <input type="date" id="postura" class="w-full p-2 border rounded-md text-sm">
                                <input type="date" id="llegada" class="w-full p-2 border rounded-md text-sm">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <input type="number" id="cantidad" placeholder="Cant. Huevos" class="w-full p-2 border rounded-md">
                            <input type="number" id="cajas" placeholder="Total Cajas" class="w-full p-2 border rounded-md">
                        </div>
                        <div class="grid grid-cols-3 gap-2">
                            <input type="text" id="camara" placeholder="Cámara" class="w-full p-2 border rounded-md">
                            <input type="text" id="rack" placeholder="Rack" class="w-full p-2 border rounded-md">
                            <input type="text" id="nivel" placeholder="Nivel" class="w-full p-2 border rounded-md">
                        </div>
                        <textarea id="obs" placeholder="Observaciones sanitarias..." class="w-full p-2 border rounded-md h-20 text-sm"></textarea>
                        <button type="button" onclick="registrarLote()" class="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-3 rounded-xl transition shadow-lg flex justify-center items-center gap-2">
                            <i data-lucide="plus-circle"></i> INGRESAR AL KARDEX
                        </button>
                    </form>
                </div>
            </section>

            <section class="lg:col-span-2">
                <div class="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden">
                    <div class="p-4 bg-slate-100 border-b flex justify-between items-center">
                        <h3 class="font-bold text-slate-700 uppercase tracking-wider">Inventario en Cámara Fría</h3>
                        <div class="flex gap-2">
                            <button onclick="exportarCSV()" class="text-xs bg-white border px-3 py-1 rounded hover:bg-slate-50">CSV</button>
                        </div>
                    </div>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 text-slate-500 text-xs uppercase">
                                    <th class="p-4">Lote / Origen</th>
                                    <th class="p-4">Ubicación</th>
                                    <th class="p-4 text-center">Edad Huevo</th>
                                    <th class="p-4 text-right">Saldo</th>
                                    <th class="p-4 text-center">Acciones</th>
                                </tr>
                            </thead>
                            <tbody id="tabla-body" class="divide-y divide-slate-100">
                                </tbody>
                        </table>
                    </div>
                </div>
            </section>
        </div>
    </main>

    <script>
        let inventario = JSON.parse(localStorage.getItem("it-kardex")) || [];

        function registrarLote() {
            const idUnico = 'LOT-' + Date.now().toString(36).toUpperCase();
            
            const nuevoLote = {
                uuid: idUnico,
                lote: document.getElementById('lote').value,
                granja: document.getElementById('granja').value,
                genetica: document.getElementById('genetica').value,
                postura: document.getElementById('postura').value,
                llegada: document.getElementById('llegada').value,
                cantidadOriginal: parseInt(document.getElementById('cantidad').value),
                saldo: parseInt(document.getElementById('cantidad').value),
                cajas: document.getElementById('cajas').value,
                ubicacion: {
                    camara: document.getElementById('camara').value,
                    rack: document.getElementById('rack').value,
                    nivel: document.getElementById('nivel').value
                },
                movimientos: [{
                    tipo: 'INGRESO',
                    fecha: new Date().toISOString(),
                    cant: document.getElementById('cantidad').value
                }]
            };

            inventario.push(nuevoLote);
            guardarYRenderizar();
            document.getElementById('form-recepcion').reset();
        }

        function calcularEdad(fechaPostura) {
            const hoy = new Date();
            const postura = new Date(fechaPostura);
            const diff = Math.floor((hoy - postura) / (1000 * 60 * 60 * 24));
            return diff;
        }

        function gestionarSalida(uuid) {
            const lote = inventario.find(l => l.uuid === uuid);
            const cant = prompt(`Cantidad a retirar del Lote ${lote.lote} (Saldo: ${lote.saldo}):`);
            
            if(cant && parseInt(cant) <= lote.saldo) {
                const tipo = confirm("¿Es para Incubación? (Cancelar para Ajuste/Merma)") ? "INCUBACION" : "MERMA/AJUSTE";
                lote.saldo -= parseInt(cant);
                lote.movimientos.push({
                    tipo: tipo,
                    fecha: new Date().toISOString(),
                    cant: parseInt(cant)
                });
                guardarYRenderizar();
            } else {
                alert("Cantidad no válida o insuficiente.");
            }
        }

        function render() {
            const tbody = document.getElementById('tabla-body');
            tbody.innerHTML = '';
            
            let totalH = 0;
            let riesgo = 0;
            let critico = 0;

            inventario.filter(l => l.saldo > 0).forEach(l => {
                const edad = calcularEdad(l.postura);
                let semaforo = 'status-optimo';
                if(edad > 10) { semaforo = 'status-critico'; critico++; }
                else if(edad > 7) { semaforo = 'status-riesgo'; riesgo++; }

                totalH += l.saldo;

                tbody.innerHTML += `
                    <tr class="${semaforo} transition-all">
                        <td class="p-4">
                            <div class="font-bold text-slate-800">${l.lote}</div>
                            <div class="text-xs text-slate-500">${l.granja} | ${l.genetica}</div>
                        </td>
                        <td class="p-4 text-xs font-mono">
                            C:${l.ubicacion.camara} R:${l.ubicacion.rack} N:${l.ubicacion.nivel}
                        </td>
                        <td class="p-4 text-center">
                            <span class="text-lg font-bold">${edad}</span> <small>días</small>
                        </td>
                        <td class="p-4 text-right font-bold text-blue-700">
                            ${l.saldo.toLocaleString()}
                        </td>
                        <td class="p-4 text-center">
                            <button onclick="gestionarSalida('${l.uuid}')" class="bg-blue-600 text-white p-2 rounded hover:bg-blue-800">
                                <i data-lucide="shuffle" class="w-4 h-4"></i>
                            </button>
                        </td>
                    </tr>
                `;
            });

            // Actualizar Dashboard
            document.getElementById('dash-huevos').innerText = totalH.toLocaleString();
            document.getElementById('dash-lotes').innerText = inventario.filter(l => l.saldo > 0).length;
            document.getElementById('dash-riesgo').innerText = riesgo;
            document.getElementById('dash-critico').innerText = critico;
            
            lucide.createIcons();
        }

        function guardarYRenderizar() {
            localStorage.setItem("it-kardex", JSON.stringify(inventario));
            render();
        }

        // Reloj y Auto-render
        setInterval(() => {
            document.getElementById('reloj').innerText = new Date().toLocaleString();
        }, 1000);

        render();
    </script>
</body>
</html>
