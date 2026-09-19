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

/* ==================== 归因分析 ==================== */

/** 归因链路的整体状态，按阶段推进 */
export type AnalysisStatus =
  | 'decomposing'   // 正在拆解问题
  | 'planning'      // 正在生成执行计划
  | 'executing'     // 正在多步执行
  | 'summarizing'   // 正在汇总结果
  | 'reporting'     // 正在生成归因报告
  | 'success'
  | 'error'
  | 'cancelled';

/** 单个计划步骤的执行状态 */
export type AnalysisStepStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

export interface AnalysisSubTask {
  task_id: string;
  task_name: string;
  task_type: string;
  description: string;
  depends_on?: string[];
  dimensions?: string[];
  metrics?: string[];
}

export interface AnalysisDecomposition {
  question_type?: string;
  analysis_goal?: string;
  subtasks: AnalysisSubTask[];
  subtask_count?: number;
}

export interface AnalysisStep {
  step_id: string;
  task_id?: string;
  step_name: string;
  task_type?: string;
  question?: string;
  description?: string;
  depends_on?: string[];
  metrics?: string[];
  dimensions?: string[];
  expected_output?: string;
  index?: number;
  total_steps?: number;
  status: AnalysisStepStatus;
  /** 流式生成中的 SQL 片段累积 */
  sqlStream?: string;
  sql?: string;
  columns?: string[];
  rows?: Record<string, any>[];
  rowCount?: number;
  formatted?: string;
  attempts?: number;
  error?: string;
  errorType?: string;
  /** 该步骤是否曾因报错重写 SQL */
  repaired?: boolean;
  /** 重试记录：mode=rewrite 表示带报错重写，retry 表示原样重试 */
  retries?: Array<{
    attempt: number;
    maxAttempts?: number;
    mode: 'rewrite' | 'retry';
    previousSql?: string;
    previousError?: string;
  }>;
}

export interface AnalysisSummary {
  completed_steps: number;
  failed_steps: number;
  skipped_steps: number;
  key_findings?: string[];
  summary_text?: string;
}

export interface AnalysisReport {
  title: string;
  executive_summary: string;
  key_findings: string[];
  root_causes: string[];
  trend_judgment: string;
  action_suggestions: string[];
  markdown?: string;
}

export interface AnalysisRecord {
  id: string;
  question: string;
  status: AnalysisStatus;
  createdAt: Date;
  analysisGoal?: string;
  questionType?: string;
  decomposition?: AnalysisDecomposition;
  steps: AnalysisStep[];
  totalSteps?: number;
  summary?: AnalysisSummary;
  report?: AnalysisReport;
  error?: string;
  errorType?: string;
  totalDurationMs?: number;
}

/** 消息流里的统一条目：区分单跳查询与多步归因 */
export type FeedItem =
  | { kind: 'query'; record: QueryRecord }
  | { kind: 'analysis'; record: AnalysisRecord };

/** 提交模式 */
export type QueryMode = 'query' | 'analyze';
