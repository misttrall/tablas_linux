📊 ETL SAP → SQL Server (Linux + systemd + Flask)

Sistema ETL desarrollado en Python para la extracción de datos desde SAP mediante RFC, transformación con pandas y carga en SQL Server, con ejecución automatizada en Linux mediante systemd y control manual vía interfaz web en Flask.


---

🚀 Características principales

Extracción de datos desde SAP usando RFC_READ_TABLE

Transformación de datos mediante pandas

Carga eficiente a SQL Server usando SQLAlchemy

Uso de tablas staging para integridad de datos

Aplicación de MERGE dinámico para sincronización incremental

Ejecución automática cada 45 minutos con systemd timer

Ejecución manual mediante interfaz web en Flask

Control de concurrencia doble:

Lock file (/tmp/etl_sap.lock)

Control en base de datos (etl_execution)


Monitoreo de estado en tiempo real (etl_state.json)

Sistema de logs persistente (etl.log)



---

🧱 Arquitectura

El sistema está compuesto por los siguientes componentes:

Orquestación

systemd service

systemd timer

Script bash (etl.sh)


Core ETL (Python)

Extracción SAP (sap_extractor.py)

Transformación (pandas)

Carga staging (staging_loader.py)

Merge final (merge_runner.py)


Persistencia

SQL Server:

Tablas staging

Tablas finales

etl_execution

etl_progress



Interfaz

Aplicación web en Flask


Observabilidad

Logs (logs/etl.log)

Estado (/tmp/etl_state.json)




---

⚙️ Instalación

1. Clonar repositorio

git clone https://github.com/misttrall/tablas_linux.git

---

2. Crear entorno virtual

python3 -m venv venv

source venv/bin/activate

pip install -r requirements.txt


---

3. Configurar variables SAP

Asegúrate de tener instalado el SDK de SAP RFC:

export SAPNWRFC_HOME=/opt/sap/nwrfcsdk

export LD_LIBRARY_PATH=/opt/sap/nwrfcsdk/lib:$LD_LIBRARY_PATH


---

4. Configuración del sistema

Editar config.json con:

Credenciales SAP

Conexión a SQL Server

Tablas a procesar

Campos por tabla



---

▶️ Ejecución manual

python etl_runner.py

O mediante script:

./etl.sh


---

🔁 Automatización con systemd

Servicio (/etc/systemd/system/etl.service)

[Unit]

Description=ETL SAP Job

[Service]

ExecStart=/opt/etl/tablas_linux/etl.sh

Restart=always


---

Timer (/etc/systemd/system/etl.timer)

[Unit]

Description=Run ETL every 45 minutes

[Timer]

OnBootSec=5min

OnUnitActiveSec=45min

[Install]

WantedBy=timers.target


---

Activación

sudo systemctl daemon-reexec

sudo systemctl daemon-reload

sudo systemctl enable etl.timer

sudo systemctl start etl.timer


---

🌐 Interfaz Web (Flask)

La aplicación Flask permite:

Disparar ejecución manual del ETL

Visualizar estado actual (etl_state.json)

Evitar ejecuciones simultáneas



---

🔐 Control de concurrencia

El sistema implementa doble validación:

1. Lock file (nivel sistema operativo)

/tmp/etl_sap.lock

Evita ejecuciones simultáneas físicas.


---

2. Control en base de datos

Tabla: etl_execution

SELECT COUNT(*) FROM etl_execution WHERE status='running'

Evita ejecuciones lógicas duplicadas.


---

🔄 Flujo ETL

1. Validación de ejecución activa


2. Creación de lock file


3. Conexión a SAP


4. Extracción de tablas


5. Transformación a DataFrame


6. Carga a staging


7. Ejecución de MERGE


8. Limpieza de staging


9. Actualización de estado y logs


10. Liberación de lock




---

📂 Estructura del proyecto

tablas_linux/

│

├── etl_runner.py

├── etl_script.py

├── etl.sh

│

├── extractor/

│ └── sap_extractor.py

│

├── db/

│ ├── db_connection.py

│ ├── staging_loader.py

│ └── merge_runner.py

│

├── utils/

│ ├── config_loader.py

│ ├── logger.py

│ └── etl_state.py

│

├── logs/

│ └── etl.log

│

├── config.json

└── venv/

---

📊 Diagramas del sistema:

Diagrama de Arquitectura


<img width="900" alt="Diagrama de arquitectura" src="https://github.com/user-attachments/assets/10eb6edd-abcd-474e-a6e4-efa3d52d81f6" />


Diagrama Arquitectura lógica


<img width="900" alt="Arquitectura Lógica" src="https://github.com/user-attachments/assets/07d60ab6-1d33-41b6-905a-63b4538e5893" />


Diagrama de flujo


<img width="900" alt="Flujo Etl" src="https://github.com/user-attachments/assets/c0e3fa9e-765f-4a72-b74f-a298b94f5aba" />


Diagrama Control de Concurrencia


<img width="900" alt="Control de Concurrencia" src="https://github.com/user-attachments/assets/9fd0ece7-bc82-4993-9a44-908b736b2fec" />


Diagrama de Secuencia


<img width="900" alt="ETL_SAP" src="https://github.com/user-attachments/assets/cae613eb-a59f-42f6-b2b6-eb83a3ad6c2a" />


Diagrama de Despliegue


<img width="900" alt="ETL_SAP_Despliegue" src="https://github.com/user-attachments/assets/b553dfd0-ab5a-445c-a0cf-1edd7f6cadcb" />


---

📊 Justificación técnica

systemd vs cron

systemd permite control de estado, reinicio automático y mejor trazabilidad.

Uso de staging

Permite aislar datos crudos, evitar inconsistencias y aplicar transformaciones seguras.

MERGE dinámico

Sincronización eficiente evitando duplicados y manteniendo integridad.

RFC_READ_TABLE

Método estándar de extracción SAP sin necesidad de desarrollo ABAP adicional.

Control de concurrencia doble

Garantiza robustez frente a ejecuciones simultáneas desde múltiples puntos.



---

📈 Posibles mejoras

Implementación de procesamiento incremental (delta loads)

Integración con herramientas de monitoreo (Prometheus, Grafana)

Containerización con Docker

Escalabilidad mediante colas (RabbitMQ, Kafka)



---

👨‍💻 Autor

Desarrollado como solución ETL empresarial en entorno Linux para integración SAP → SQL Server.


---
