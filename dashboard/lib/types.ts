// ETL Status Types
export type ETLStatus = "idle" | "running" | "success" | "failed" | "warning";

export interface ETLState {
  status: ETLStatus;
  currentStep: string;
  progress: number;
  startTime: string | null;
  endTime: string | null;
  executionId: string | null;
  triggeredBy: "manual" | "scheduled" | null;
  isLocked: boolean;
}

export interface ETLExecution {
  id: string;
  startTime: string;
  endTime: string | null;
  status: ETLStatus;
  triggeredBy: "manual" | "scheduled";
  totalRecords: number;
  tablesProcessed: number;
  duration: number | null; // in seconds
  errorMessage: string | null;
}

export interface TableMetrics {
  tableName: string;
  recordsExtracted: number;
  recordsLoaded: number;
  executionTime: number; // in seconds
  lastUpdated: string;
  status: "success" | "failed" | "pending";
}

export interface ETLError {
  id: string;
  executionId: string;
  timestamp: string;
  errorType: "extraction" | "transformation" | "loading" | "connection" | "validation";
  tableName: string | null;
  message: string;
  stackTrace: string | null;
  severity: "low" | "medium" | "high" | "critical";
  resolved: boolean;
}

export interface Alert {
  id: string;
  type: "error" | "warning" | "info";
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  executionId: string | null;
}

export interface DailyMetrics {
  date: string;
  totalRecords: number;
  executionTime: number;
  successRate: number;
  errorsCount: number;
}

export interface ETLStats {
  totalExecutions: number;
  successfulExecutions: number;
  failedExecutions: number;
  averageExecutionTime: number;
  totalRecordsProcessed: number;
  lastSuccessfulRun: string | null;
}
