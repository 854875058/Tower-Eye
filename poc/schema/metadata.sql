PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  media_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  file_name TEXT,
  sha256 TEXT,
  width INTEGER,
  height INTEGER,
  duration_sec REAL,
  captured_at TEXT,
  lat REAL,
  lon REAL,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assets_captured_at ON assets(captured_at);
CREATE INDEX IF NOT EXISTS idx_assets_location ON assets(lat, lon);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  asset_id TEXT,
  event_type TEXT,
  alarm_level TEXT,
  alarm_source TEXT,
  alarm_time TEXT,
  lat REAL,
  lon REAL,
  region TEXT,
  extra_json TEXT,
  summary TEXT,
  description TEXT,
  address TEXT,
  device_name TEXT,
  confidence_level REAL,
  -- 地理信息
  province_name TEXT,
  city_name TEXT,
  county_name TEXT,
  town_code TEXT,
  town_name TEXT,
  -- 设备信息
  device_code TEXT,
  channel_code TEXT,
  channel_name TEXT,
  -- 告警详情
  warning_order_id TEXT,
  warning_type_id TEXT,
  alarm_body TEXT,
  algorithm_code TEXT,
  algorithm_name TEXT,
  emergency_level TEXT,
  importance_level TEXT,
  order_status TEXT,
  confidence_level_max REAL,
  tenant_name TEXT,
  -- 媒体本地路径
  video_path TEXT,
  img_src_path TEXT,
  img_icon_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_events_alarm_time ON events(alarm_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_summary ON events(summary);
CREATE INDEX IF NOT EXISTS idx_events_town ON events(town_name);
CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_code);
CREATE INDEX IF NOT EXISTS idx_events_address ON events(address);
CREATE INDEX IF NOT EXISTS idx_events_county ON events(county_name);

CREATE TABLE IF NOT EXISTS detections (
  detection_id TEXT PRIMARY KEY,
  asset_id TEXT,
  model_name TEXT,
  label TEXT,
  confidence REAL,
  bbox_x REAL,
  bbox_y REAL,
  bbox_w REAL,
  bbox_h REAL,
  frame_index INTEGER,
  timestamp_sec REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_detections_label ON detections(label);

CREATE TABLE IF NOT EXISTS annotations (
  annotation_id TEXT PRIMARY KEY,
  asset_id TEXT,
  label TEXT,
  bbox_x REAL,
  bbox_y REAL,
  bbox_w REAL,
  bbox_h REAL,
  origin TEXT,
  reviewer TEXT,
  reviewed_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_annotations_label ON annotations(label);

CREATE TABLE IF NOT EXISTS embeddings (
  embedding_id TEXT PRIMARY KEY,
  asset_id TEXT,
  model_name TEXT,
  vector_path TEXT,
  dims INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_name);

CREATE TABLE IF NOT EXISTS scene_bindings (
  binding_id TEXT PRIMARY KEY,
  asset_id TEXT,
  scene_name TEXT,
  confidence REAL,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_scene_bindings_scene ON scene_bindings(scene_name);

CREATE TABLE IF NOT EXISTS qa_cache (
  query_id TEXT PRIMARY KEY,
  query_text TEXT,
  answer_text TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
