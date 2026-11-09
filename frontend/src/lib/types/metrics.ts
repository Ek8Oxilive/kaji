/** Serveurs de métriques (`docs/api/metriques.md`). Les secrets ne sont jamais renvoyés : seulement `token_set` / `otel_headers_set`. */
export type MetricsType = "influxdb" | "graphite" | "opentelemetry";
export type MetricsRow = { id: string; type: MetricsType; server: string | null; port: number | null; disable: boolean };
export type MetricsServer = MetricsRow & {
  digest: string | null;
  influxdbproto?: string | null; organization?: string | null; bucket?: string | null; max_body_size?: number | null; mtu?: number | null; verify_certificate?: boolean | null; api_path_prefix?: string | null; token_set?: boolean;
  proto?: string | null; path?: string | null; timeout?: number | null;
  otel_protocol?: string | null; otel_path?: string | null; otel_timeout?: number | null; otel_compression?: string | null; otel_verify_ssl?: boolean | null; otel_max_body_size?: number | null;
  otel_resource_attributes_set?: boolean; otel_headers_set?: boolean;
};
export type MetricsPreview = { dry_run: true; params: Record<string, string | number>; remove?: string[]; needs_confirm: boolean };
export const TYPE_LABEL: Record<MetricsType, string> = { influxdb: "InfluxDB", graphite: "Graphite", opentelemetry: "OpenTelemetry" };
