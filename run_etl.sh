#!/bin/bash

cd /opt/etl/tablas_linux

export SAPNWRFC_HOME=/opt/sap/nwrfcsdk
export LD_LIBRARY_PATH=/opt/sap/nwrfcsdk/lib:$LD_LIBRARY_PATH

/opt/etl/tablas_linux/venv/bin/python etl_runner.py
