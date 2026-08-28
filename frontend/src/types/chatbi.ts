export type QueryStatus = 
  | 'generating_sql' 
  | 'executing_query' 
  | 'success' 
  | 'error' 
  | 'cancelled';

export interface QueryRecord {
  id: string;
  question: string;
  sql: string;
  status: QueryStatus;
  columns?: string[];
  rows?: Record<string, any>[];
  rowCount?: number;
  formatted?: string;
  sqlDurationMs?: number;
  totalDurationMs?: number;
  error?: string;
  errorType?: string;
  createdAt: Date;
}

export interface StreamEventData {
  content?: string;
  sql?: string;
  tokens?: number;
  columns?: string[];
  rows?: Record<string, any>[];
  row_count?: number;
  formatted?: string;
  error?: string;
  error_type?: string;
  metadata?: Record<string, any>;
}

export interface HealthState {
  status: 'ok' | 'error' | 'checking';
  databaseConnected: boolean;
  message?: string;
}
