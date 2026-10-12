export interface User { id: number; email: string; display_name: string; is_admin: boolean; is_active: boolean }
export interface Me { user: User; csrf_token: string | null }

export interface Project { id: number; name: string; description: string; is_demo: boolean; role: "owner" | "analyst" | "viewer"; created_at: string }

export interface DatasetVersion {
  id: number; version: number; status: "validated" | "needs_review" | "approved" | "rejected"; format: string;
  stats: { records: number; objects: number; errors: number; warnings: number; with_covariance: number; kinds: Record<string, number> };
  provenance: Record<string, unknown>; snapshot_sha256: string; reference_time: string; created_at: string; approved_at: string | null;
}
export interface Dataset { id: number; name: string; is_synthetic: boolean; created_at: string; versions: DatasetVersion[] }
export interface Transformation { id: number; kind: string; description: string; status: string; result_version_id: number | null }
export interface DatasetVersionDetail extends DatasetVersion {
  dataset: { id: number; name: string; is_synthetic: boolean };
  file: { name: string; sha256: string; size_bytes: number; origin: string; uploaded_at: string };
  finding_counts: Record<string, number>;
  transformations: Transformation[];
}
export interface Finding { id: number; severity: "error" | "warning" | "info"; code: string; message: string; record: string | null; suggestion: string | null }

export interface CatalogueRow {
  object_id: string; object_name: string | null; kind: string; format: string; epoch: string; frame: string; has_covariance: boolean;
  perigee_alt_km: number | null; apogee_alt_km: number | null; inclination_deg: number | null; period_min: number | null; usable: boolean; source_ref: string | null;
}

export interface Job {
  id: number; kind: "screening" | "cdm_assessment"; status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  dataset_version_id: number; config: Record<string, unknown>; config_sha256: string; progress: number; progress_message: string;
  attempts: number; error_category: string | null; error_message: string | null; stats: Record<string, unknown>; warnings: string[];
  software: Record<string, unknown>; rerun_of: number | null; created_at: string; started_at: string | null; finished_at: string | null; cancel_requested: boolean;
}

export interface Geometry {
  miss_km: number; rel_speed_km_s: number; rel_pos_km: number[]; rel_vel_km_s: number[]; rel_pos_rtn_km: number[]; rel_vel_rtn_km_s: number[];
  approach_angle_deg: number; encounter_plane_basis: number[][]; miss_in_plane_km: number[]; range_rate_km_s: number;
}

export interface Encounter {
  id: number; job_id: number; primary_id: string; secondary_id: string; primary_name: string | null; secondary_name: string | null;
  tca_utc: string; miss_km: number; rel_speed_km_s: number; geometry: Geometry; frame: string; refinement_status: string; flags: string[];
  data_age_days: Record<string, number>; propagators: Record<string, string>; covariance_available: "both" | "partial" | "none";
  pc_status: string; pc_value: number | null; ml_priority_experimental: number | null; ml_model: string | null;
}

export interface PcResult {
  status: string; value: number | null; method: string | null; reasons: string[]; warnings: string[];
  details: {
    hbr_km?: number; miss_in_plane_km?: number[]; projected_cov_km2?: number[][]; sigma_major_km?: number; sigma_minor_km?: number;
    encounter_duration_est_s?: number; monte_carlo_crosscheck?: { value: number; ci95: [number, number]; samples: number; seed: number };
    originator?: { pc: number | null; method: string | null; miss_distance_m: number | null; note: string };
  };
}

export interface EncounterDetail extends Encounter {
  job: Job;
  probability: { method: string; algorithm_version: string; status: string; value: number | null; result: PcResult }[];
  dataset: { id: number; name: string; version: number; synthetic: boolean; snapshot_sha256: string };
  history: { encounter_id: number; job_id: number; tca_utc: string; miss_km: number }[];
}

export interface RelativeMotion { encounter_id: number; tca_utc: string; frame: string; data_kind: string; t_s: number[]; rtn_km: number[][]; range_km: number[] }

export interface ScenarioArm { tca_utc: string | null; miss_km: number | null; rel_speed_km_s: number | null }
export interface Scenario {
  id: number; name: string; params: Record<string, number | boolean | string | null>; created_at: string; algorithm_version?: string;
  result: {
    label: string; baseline: ScenarioArm; alternative: ScenarioArm; miss_change_km: number | null; dv_magnitude_m_s: number; propellant_kg: number | null;
    displacement_at_tca_km: number | null; others_checked?: number; other_encounters: { primary: string; secondary: string; tca_utc: string; geometry: Geometry }[];
    warnings: string[]; model: string; algorithm: string;
  };
}

export interface VizObject { object_id: string; name: string | null; r_km: number[]; v_km_s: number[]; age_days: number; kind: string; method: string }
export interface VizPositions { at_utc: string; frame: string; earth_rotation_angle_deg: number; earth_rotation_uses_ut1: boolean; objects: VizObject[]; not_shown: number; notes: string[]; data_kind: string }
export interface Trajectory { object_id: string; frame: string; start_utc: string; t_s: number[]; r_km: number[][]; data_kind: string }

export interface Report { id: number; job_id: number; format: string; sha256: string; generator_version: string; created_at: string }

export interface MLMetricsBlock {
  n: number; positives: number; prevalence: number; average_precision: number; pr_curve: { precision: number[]; recall: number[] };
  precision?: number; recall?: number; false_negative_rate?: number; false_positive_rate?: number; brier?: number; threshold?: number;
  confusion_matrix?: { tn: number; fp: number; fn: number; tp: number };
  calibration?: { fraction_positive: number[]; mean_predicted: number[] };
  by_regime?: Record<string, { n: number; average_precision: number }>;
}
export interface MLModel {
  id: number; name: string; version: string; status: string; training_data_origin: string; training_data_sha256: string; artefact_sha256: string;
  params: Record<string, unknown>; metrics: { test: Record<string, MLMetricsBlock>; split_sizes: Record<string, number> };
  feature_schema: { version: string; features: string[] }; seed: number; code_version: string; created_at: string; label: string;
}

export interface Paged<T> { total: number; items: T[] }

export interface TrackObject { object_id: string; name: string | null; kind: string; age_days: number; r: (number | null)[] }
export interface Tracks {
  start_utc: string; step_s: number; samples: number; frame: string; total_objects: number; shown_objects: number;
  objects: TrackObject[]; notes: string[]; data_kind: string;
}

export interface ManeuverOption {
  lead_orbits: number; lead_minutes: number; burn_utc: string; direction: string; direction_text: string; dv_m_s: number;
  dv_rtn_m_s: number[]; miss_km: number; change_km: number; km_per_m_s: number; tca_shift_s: number | null; too_late: boolean;
}
export interface ManeuverOptions {
  encounter_id: number; primary: string; secondary: string; screening_miss_km: number; label: string; baseline_miss_km: number;
  baseline_tca_utc: string; orbital_period_min: number; leads: { lead_orbits: number; lead_minutes: number; burn_utc: string; too_late: boolean }[];
  options: ManeuverOption[]; model: string; algorithm: string; caveats: string[];
}
