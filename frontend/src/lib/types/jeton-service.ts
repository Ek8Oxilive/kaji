/** Jeton de SERVICE d'une connexion (`GET /api/connections/{id}/service-token`, `docs/api/jeton-service.md`) : celui du planificateur et des alertes. Le secret n'est jamais renvoyé. */
import type { UserTokenState } from "./jeton-utilisateur";

export type ServiceToken = {
  conn_id: number;
  name: string;
  state: UserTokenState;
  pve_user: string | null;
  token_id: string | null;
  expires_at: string | null;
  days_left: number | null;
  verified: boolean | null;
  created_by: string | null;
  /** droits minimaux qui manquent au jeton qu'on vient d'enregistrer (le planificateur échouerait) */
  lacks: string[] | null;
};

export type ServiceTokenInfo = {
  enabled: boolean;
  problem: string | null;
  /** KAJI_REQUIRE_SERVICE_TOKEN : sans jeton de service, le planificateur et les alertes ne font rien pour cette connexion */
  required: boolean;
  max_days: number;
  /** les SEULS privilèges qu'un jeton de service peut détenir */
  allowed_privileges: string[];
  token: ServiceToken;
};
