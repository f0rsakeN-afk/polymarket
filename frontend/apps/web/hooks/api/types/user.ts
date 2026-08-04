export interface MeResponse {
  id: string;
  email: string;
  username: string;
  is_email_verified: boolean;
  is_admin: boolean;
  is_2fa_enabled: boolean;
  referral_code?: string;
}

export interface Session {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  last_active_at: string;
  expires_at: string;
}
