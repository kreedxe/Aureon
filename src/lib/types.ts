export interface BackendConfig {
  baseUrl: string;
  token: string;
}

export type LanguageChoice = "auto" | "uz" | "ru" | "en";
export type AIAction = "summary" | "key_points" | "action_items" | "translation";
export type ConversationState =
  | "IDLE"
  | "INITIALIZING"
  | "GREETING"
  | "LISTENING"
  | "TRANSCRIBING"
  | "THINKING"
  | "SPEAKING"
  | "INTERRUPTED"
  | "ERROR"
  | "ENDED";

export interface LocalVoice {
  id: string;
  name: string;
  language: string;
}

export interface ConversationReadiness {
  ready: boolean;
  vad_ready: boolean;
  whisper_ready: boolean;
  llm_ready: boolean;
  voices: LocalVoice[];
  install_status: "idle" | "running" | "completed" | "failed";
  install_progress: number;
  install_message: string;
  install_error: string | null;
}

export interface ConversationSummary {
  title: string;
  customer_name: string;
  customer_age: string;
  customer_location: string;
  other_customer_details: string[];
  customer_interests: string[];
  customer_needs: string[];
  purchase_intent: "browsing" | "comparing" | "interested" | "committed" | "unknown";
  purchase_outcome:
    | "purchased"
    | "requested_more_information"
    | "undecided"
    | "no_purchase";
  tone: string;
  important_details: string[];
  next_steps: string[];
}

export interface ConversationMessageRecord {
  id: number;
  role: "user" | "assistant";
  text: string;
  language: Exclude<LanguageChoice, "auto">;
  timestamp: string;
  language_probability: number | null;
}

export interface ConversationListItem {
  id: string;
  title: string;
  language: LanguageChoice;
  started_at: string;
  ended_at: string | null;
  status: "active" | "completed" | "failed";
  message_count: number;
}

export interface ConversationDetail extends ConversationListItem {
  messages: ConversationMessageRecord[];
  summary: ConversationSummary | null;
  summary_error: string | null;
}

export interface ConversationTranscript {
  role: "user" | "assistant";
  text: string;
  language: Exclude<LanguageChoice, "auto">;
  languageProbability?: number;
  timestamp?: string;
}
export type TranscriptionStatus =
  | "not_transcribed"
  | "queued"
  | "loading_model"
  | "transcribing"
  | "completed"
  | "failed";

export interface Transcription {
  text: string;
  language: string;
  language_probability: number;
  model: string;
}

export interface AISummary {
  operation: "summary";
  language: Exclude<LanguageChoice, "auto">;
  summary: string;
  model: string;
}

export interface AIKeyPoints {
  operation: "key_points";
  language: Exclude<LanguageChoice, "auto">;
  key_points: string[];
  model: string;
}

export interface AIActionItems {
  operation: "action_items";
  language: Exclude<LanguageChoice, "auto">;
  action_items: { task: string; owner: string | null; due: string | null }[];
  decisions: string[];
  model: string;
}

export interface AITranslation {
  operation: "translation";
  source_language: Exclude<LanguageChoice, "auto">;
  target_language: Exclude<LanguageChoice, "auto">;
  translation: string;
  model: string;
}

export type AIResult = AISummary | AIKeyPoints | AIActionItems | AITranslation;

export type AIJobStatus =
  | "queued"
  | "downloading"
  | "loading_model"
  | "processing"
  | "completed"
  | "failed";

export interface AIJob {
  id: string;
  recording_id: string;
  operation: AIAction;
  status: AIJobStatus;
  progress: number;
  message: string;
  error: string | null;
  result: AIResult | null;
}

export interface AIModelStatus {
  name: string;
  filename: string;
  size_bytes: number;
  downloaded: boolean;
  loaded: boolean;
  status: "not_downloaded" | "downloaded" | "loaded" | "loading" | "failed";
  error: string | null;
}

export interface Recording {
  id: string;
  name: string;
  created_at: string;
  duration: number;
  media_type: string;
  transcription: Transcription | null;
  transcription_status: TranscriptionStatus;
  ai_results: Partial<Record<AIAction, AIResult>>;
  audioUrl: string | null;
}

export interface RecordingList {
  recordings: Omit<Recording, "audioUrl">[];
}

export interface TranscriptionJob {
  id: string;
  recording_id: string;
  status: TranscriptionStatus;
  progress: number;
  message: string;
  error: string | null;
  transcription: Transcription | null;
}

export type ProductAvailability = "available" | "out_of_stock" | "discontinued";
export type ProductSort = "name" | "price" | "stock";

export interface Product {
  id: string;
  name: string;
  description: string | null;
  price: string;
  currency: string;
  stock_quantity: number;
  category: string;
  brand: string | null;
  specifications: Record<string, string | number | boolean | null>;
  availability: ProductAvailability;
  created_at: string;
  updated_at: string;
}

export interface ProductInput {
  name: string;
  description: string | null;
  price: string;
  currency: string;
  stock_quantity: number;
  category: string;
  brand: string | null;
  specifications: Record<string, string | number | boolean | null>;
  availability: "available" | "discontinued";
}

export interface ProductList {
  products: Product[];
  categories: string[];
  total: number;
}

export interface ProductDescriptionDraft {
  description: string;
  requires_review: true;
}
