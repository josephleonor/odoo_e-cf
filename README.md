# RACO e-CF: laboratorio de integración, Odoo 18 Community

**Estado: prototipo de pruebas. No emite e-CF válidos, no firma XML ni se conecta a DGII.**
No instalar en la base de producción para facturar. El campo e-NCF se introduce manualmente solo como identificador ficticio y no reserva secuencias.

## Funciona ahora

- Complemento Odoo instalable con lista, formulario y vínculo a factura publicada.
- Casos de laboratorio E31, E32 y E34, en DOP. Se bloquean los otros tipos hasta implementar sus XSD.
- Preparación de fixture JSON, envío local, TrackId, consulta de estado y registro de respuestas.
- Rangos ficticios por compañía y tipo, asignación con bloqueo de concurrencia y control de vencimiento; puede seguir usando números manuales ficticios.
- Validación de tipo, longitud del e-NCF, datos básicos, líneas y RNC del comprador para E31. El fixture registra subtotales, impuesto y totales calculados por Odoo.
- Botón «e-CF pruebas» en la factura para consultar sus documentos de laboratorio.
- Simulador local determinista, con aceptación en la segunda consulta e idempotencia para el mismo contenido.
- Acceso de escritura limitado a administradores contables; el servicio simulado escucha solo en loopback.

## Ejecutar

1. En una máquina de pruebas con Odoo 18 Community y módulos `account` y `l10n_do`, agregar el directorio que contiene `raco_ecf` a `addons_path`.
2. Ejecutar `python3 simulator/server.py` desde la raíz del paquete. El simulador escucha en `127.0.0.1:8765`.
3. Actualizar la lista de aplicaciones de Odoo e instalar **RACO e-CF Laboratory** en una base de pruebas. Reiniciar Odoo tras añadir el directorio.
4. Crear y publicar una factura de prueba en DOP. En **Contabilidad → e-CF laboratorio**, crear documento vinculado a la factura, tipo `31`, e-NCF ficticio `E310000000001`; pulsar **Preparar**, **Enviar a simulador**, **Consultar resultado** dos veces.
5. Para otro puerto local, establecer `raco_ecf.lab_url` en Parámetros del sistema; solo se admiten `localhost` y `127.0.0.1`.
6. Ejecutar `python3 -m unittest discover -s tests -v` para verificar el simulador.

Para probar la asignación automática: abrir **Contabilidad → e-CF laboratorio → Rangos ficticios**, crear un rango E32 para RACO e-CF LAB (inicio 2, fin 100, siguiente 2, vencimiento futuro); después crear otro documento de laboratorio sin e-NCF y pulsar **Asignar e-NCF ficticio**. Los números asignados nunca deben usarse ante DGII.

## Pendiente para certificar con DGII

| Bloque | Implementación pendiente y criterio de aceptación |
| --- | --- |
| Datos fiscales | Mapear impuestos, exenciones, descuentos, formas de pago, moneda, RNC y reglas por tipo conforme al formato DGII; pruebas de cálculos y redondeo. |
| Secuencias | Reemplazar los rangos ficticios por rangos **autorizados** por DGII; verificar autorización, importación segura, cancelación y trazabilidad fiscal. |
| XML | Reemplazar el fixture JSON por ECF/RFCE/ARECF/ACECF/ANECF; validar contra XSD oficiales vigentes y pruebas de cada tipo 31, 32, 33, 34, 41, 43, 44, 45, 46, 47. |
| Criptografía | Firmar XML y semilla con certificado tributario en bóveda segura; comprobar firma localmente, caducidad y rotación. Nunca guardar clave privada o contraseña en parámetros de Odoo. |
| Transporte | Cliente DGII separado por pre-certificación, certificación y producción; autenticación por semilla/token, recepción, RFCE inferior a RD$250,000, consulta de resultado, reintentos seguros y auditoría. |
| Receptor | Servicios HTTPS públicos para recibir e-CF y aprobaciones comerciales, validar firma y esquema, generar acuse síncrono y respuesta comercial; controles de acceso y registro de entrega. |
| Documentos | Representación impresa y QR oficiales, conservación del XML firmado y respuestas, envío al receptor tras estado satisfactorio, contingencia, anulaciones y notas vinculadas. |
| Homologación | Solicitud DGII, datos de software/URLs, sets de datos, respuestas comerciales, simulación, autorización y pruebas de extremo a extremo en los ambientes oficiales. |

**No se incluyen certificado, credenciales, XSD ni URL productiva.** La instalación de este prototipo no constituye certificación ni habilita facturación electrónica legal.

Documentación DGII: https://dgii.gov.do/cicloContribuyente/facturacion/comprobantesFiscalesElectronicosE-CF/Paginas/documentacionSobreE-CF.aspx

Servicios DGII: https://dgii.gov.do/cicloContribuyente/facturacion/comprobantesFiscalesElectronicosE-CF/Documentacin%20sobre%20eCF/Informe%20y%20Descripci%C3%B3n%20T%C3%A9cnica/Descripcion%20Tecnica%20Servicios%20DGII.pdf
