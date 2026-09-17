import { d1 } from './selfhost-d1';

export const env = {
  get DB() { return d1; },
  get VESSEL_AUTH_SECRET() { return process.env.VESSEL_AUTH_SECRET ?? ''; },
  get VESSEL_AUTH_URL() { return process.env.VESSEL_AUTH_URL ?? ''; },
  get RESEND_API_KEY() { return process.env.RESEND_API_KEY ?? ''; },
};
