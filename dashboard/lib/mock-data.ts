import type {
  ETLState,
  ETLExecution,
  TableMetrics,
  ETLError,
  Alert,
  DailyMetrics,
  ETLStats,
} from "./types";

// Current ETL State (simulating idle state)
export const mockETLState: ETLState = {
  status: "idle",
  currentStep: "",
  progress: 0,
  startTime: null,
  endTime: null,
  executionId: null,
  triggeredBy: null,
  isLocked: false,
};

// Simulated running state for testing
export const mockETLStateRunning: ETLState = {
  status: "running",
  currentStep: "Extrayendo datos de MARA",
  progress: 45,
  startTime: new Date(Date.now() - 15 * 60 * 1000).toISOString(), // 15 min ago
  endTime: null,
  executionId: "exec-2024-001",
  triggeredBy: "scheduled",
  isLocked: true,
};

// Execution History
export const mockExecutions: ETLExecution[] = [
  {
    id: "exec-2024-010",
    startTime: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
    endTime: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
    triggeredBy: "scheduled",
    totalRecords: 125430,
    tablesProcessed: 8,
    duration: 1980,
    errorMessage: null,
  },
  {
    id: "exec-2024-009",
    startTime: new Date(Date.now() - 90 * 60 * 1000).toISOString(),
    endTime: new Date(Date.now() - 58 * 60 * 1000).toISOString(),
    status: "success",
    triggeredBy: "scheduled",
    totalRecords: 124890,
    tablesProcessed: 8,
    duration: 1920,
    errorMessage: null,
  },
  {
    id: "exec-2024-008",
    startTime: new Date(Date.now() - 135 * 60 * 1000).toISOString(),
    endTime: new Date(Date.now() - 110 * 60 * 1000).toISOString(),
    status: "failed",
    triggeredBy: "manual",
    totalRecords: 45000,
    tablesProcessed: 3,
    duration: 1500,
    errorMessage: "Connection timeout to SAP server",
  },
  {
    id: "exec-2024-007",
    startTime: new Date(Date.now() - 180 * 60 * 1000).toISOString(),
    endTime: new Date(Date.now() - 148 * 60 * 1000).toISOString(),
    status: "success",
    triggeredBy: "scheduled",
    totalRecords: 126200,
    tablesProcessed: 8,
    duration: 1920,
    errorMessage: null,
  },
  {
    id: "exec-2024-006",
    startTime: new Date(Date.now() - 225 * 60 * 1000).toISOString(),
    endTime: new Date(Date.now() - 193 * 60 * 1000).toISOString(),
    status: "success",
    triggeredBy: "scheduled",
    totalRecords: 125800,
    tablesProcessed: 8,
    duration: 1920,
    errorMessage: null,
  },
];

// Table Metrics (SAP Tables)
export const mockTableMetrics: TableMetrics[] = [
  {
    tableName: "MARA",
    recordsExtracted: 45230,
    recordsLoaded: 45230,
    executionTime: 245,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "MARC",
    recordsExtracted: 38450,
    recordsLoaded: 38450,
    executionTime: 198,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "MARD",
    recordsExtracted: 22100,
    recordsLoaded: 22100,
    executionTime: 156,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "MBEW",
    recordsExtracted: 12450,
    recordsLoaded: 12450,
    executionTime: 89,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "MAKT",
    recordsExtracted: 5200,
    recordsLoaded: 5200,
    executionTime: 45,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "LFA1",
    recordsExtracted: 1200,
    recordsLoaded: 1200,
    executionTime: 23,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "EKKO",
    recordsExtracted: 650,
    recordsLoaded: 650,
    executionTime: 18,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
  {
    tableName: "EKPO",
    recordsExtracted: 150,
    recordsLoaded: 150,
    executionTime: 12,
    lastUpdated: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    status: "success",
  },
];

// ETL Errors
export const mockErrors: ETLError[] = [
  {
    id: "err-001",
    executionId: "exec-2024-008",
    timestamp: new Date(Date.now() - 110 * 60 * 1000).toISOString(),
    errorType: "connection",
    tableName: null,
    message: "Connection timeout to SAP server after 30 seconds",
    stackTrace:
      "pyrfc.RFCCommunicationError: RFC_COMMUNICATION_FAILURE\n  at SAPConnection.connect()\n  at extract_table()",
    severity: "critical",
    resolved: false,
  },
  {
    id: "err-002",
    executionId: "exec-2024-005",
    timestamp: new Date(Date.now() - 300 * 60 * 1000).toISOString(),
    errorType: "validation",
    tableName: "MARA",
    message: "Data validation failed: NULL values in required field MATNR",
    stackTrace: null,
    severity: "medium",
    resolved: true,
  },
  {
    id: "err-003",
    executionId: "exec-2024-003",
    timestamp: new Date(Date.now() - 480 * 60 * 1000).toISOString(),
    errorType: "loading",
    tableName: "MBEW",
    message: "Deadlock detected during MERGE operation",
    stackTrace:
      "pyodbc.OperationalError: (1205, 'Transaction was deadlocked')\n  at merge_table()\n  at load_data()",
    severity: "high",
    resolved: true,
  },
];

// Alerts
export const mockAlerts: Alert[] = [
  {
    id: "alert-001",
    type: "error",
    title: "ETL Execution Failed",
    message:
      "La ejecución exec-2024-008 falló debido a timeout de conexión con SAP",
    timestamp: new Date(Date.now() - 110 * 60 * 1000).toISOString(),
    read: false,
    executionId: "exec-2024-008",
  },
  {
    id: "alert-002",
    type: "warning",
    title: "Tiempo de ejecución elevado",
    message:
      "La última ejecución tomó 33 minutos, 10% más que el promedio",
    timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    read: false,
    executionId: "exec-2024-010",
  },
  {
    id: "alert-003",
    type: "info",
    title: "Ejecución completada",
    message: "ETL exec-2024-010 completado exitosamente con 125,430 registros",
    timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    read: true,
    executionId: "exec-2024-010",
  },
];

// Daily Metrics for charts (last 7 days)
export const mockDailyMetrics: DailyMetrics[] = [
  {
    date: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 498000,
    executionTime: 7200,
    successRate: 100,
    errorsCount: 0,
  },
  {
    date: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 512000,
    executionTime: 7450,
    successRate: 93.75,
    errorsCount: 1,
  },
  {
    date: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 485000,
    executionTime: 6980,
    successRate: 100,
    errorsCount: 0,
  },
  {
    date: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 520000,
    executionTime: 7600,
    successRate: 100,
    errorsCount: 0,
  },
  {
    date: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 495000,
    executionTime: 7100,
    successRate: 87.5,
    errorsCount: 2,
  },
  {
    date: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    totalRecords: 501000,
    executionTime: 7250,
    successRate: 100,
    errorsCount: 0,
  },
  {
    date: new Date().toISOString().split("T")[0],
    totalRecords: 250000,
    executionTime: 3960,
    successRate: 87.5,
    errorsCount: 1,
  },
];

// Overall Stats
export const mockStats: ETLStats = {
  totalExecutions: 156,
  successfulExecutions: 148,
  failedExecutions: 8,
  averageExecutionTime: 1920, // 32 minutes
  totalRecordsProcessed: 19_500_000,
  lastSuccessfulRun: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
};
