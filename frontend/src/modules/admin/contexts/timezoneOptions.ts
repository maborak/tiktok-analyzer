/**
 * Curated timezone list for the live-detail dropdown.
 *
 * Full Intl tz support reaches ~600 zones (Intl.supportedValuesOf
 * 'timeZone'); a select with that many entries is unusable. The
 * curated list below covers every region we've actually seen TikTok
 * creators broadcast from, plus UTC. The browser's auto-detected zone
 * is added at runtime by the dropdown component if it's not already
 * in this list, so users in obscure zones still see their own.
 */

export interface TimezoneOption {
  value: string;     // IANA name
  label: string;     // human-readable label
  region: string;    // group header for the dropdown
}

export const TIMEZONE_OPTIONS: TimezoneOption[] = [
  { value: 'UTC',                 label: 'UTC',                          region: 'Reference' },

  { value: 'America/Lima',        label: 'Lima (PET)',                   region: 'Americas' },
  { value: 'America/Bogota',      label: 'Bogotá (COT)',                 region: 'Americas' },
  { value: 'America/Mexico_City', label: 'Mexico City (CST/CDT)',        region: 'Americas' },
  { value: 'America/Buenos_Aires',label: 'Buenos Aires (ART)',           region: 'Americas' },
  { value: 'America/Sao_Paulo',   label: 'São Paulo (BRT)',              region: 'Americas' },
  { value: 'America/Caracas',     label: 'Caracas (VET)',                region: 'Americas' },
  { value: 'America/Santiago',    label: 'Santiago (CLT)',               region: 'Americas' },
  { value: 'America/Los_Angeles', label: 'Los Angeles (PT)',             region: 'Americas' },
  { value: 'America/Denver',      label: 'Denver (MT)',                  region: 'Americas' },
  { value: 'America/Chicago',     label: 'Chicago (CT)',                 region: 'Americas' },
  { value: 'America/New_York',    label: 'New York (ET)',                region: 'Americas' },
  { value: 'America/Toronto',     label: 'Toronto (ET)',                 region: 'Americas' },
  { value: 'America/Anchorage',   label: 'Anchorage (AKT)',              region: 'Americas' },
  { value: 'Pacific/Honolulu',    label: 'Honolulu (HST)',               region: 'Americas' },

  { value: 'Europe/London',       label: 'London (GMT/BST)',             region: 'Europe' },
  { value: 'Europe/Lisbon',       label: 'Lisbon (WET)',                 region: 'Europe' },
  { value: 'Europe/Madrid',       label: 'Madrid (CET/CEST)',            region: 'Europe' },
  { value: 'Europe/Paris',        label: 'Paris (CET/CEST)',             region: 'Europe' },
  { value: 'Europe/Berlin',       label: 'Berlin (CET/CEST)',            region: 'Europe' },
  { value: 'Europe/Rome',         label: 'Rome (CET/CEST)',              region: 'Europe' },
  { value: 'Europe/Athens',       label: 'Athens (EET/EEST)',            region: 'Europe' },
  { value: 'Europe/Istanbul',     label: 'Istanbul (TRT)',               region: 'Europe' },
  { value: 'Europe/Moscow',       label: 'Moscow (MSK)',                 region: 'Europe' },

  { value: 'Africa/Lagos',        label: 'Lagos (WAT)',                  region: 'Africa & MEast' },
  { value: 'Africa/Cairo',        label: 'Cairo (EET)',                  region: 'Africa & MEast' },
  { value: 'Africa/Johannesburg', label: 'Johannesburg (SAST)',          region: 'Africa & MEast' },
  { value: 'Asia/Dubai',          label: 'Dubai (GST)',                  region: 'Africa & MEast' },
  { value: 'Asia/Tehran',         label: 'Tehran (IRST)',                region: 'Africa & MEast' },

  { value: 'Asia/Karachi',        label: 'Karachi (PKT)',                region: 'Asia' },
  { value: 'Asia/Kolkata',        label: 'Kolkata (IST)',                region: 'Asia' },
  { value: 'Asia/Bangkok',        label: 'Bangkok (ICT)',                region: 'Asia' },
  { value: 'Asia/Jakarta',        label: 'Jakarta (WIB)',                region: 'Asia' },
  { value: 'Asia/Singapore',      label: 'Singapore (SGT)',              region: 'Asia' },
  { value: 'Asia/Hong_Kong',      label: 'Hong Kong (HKT)',              region: 'Asia' },
  { value: 'Asia/Shanghai',       label: 'Shanghai (CST)',               region: 'Asia' },
  { value: 'Asia/Manila',         label: 'Manila (PHT)',                 region: 'Asia' },
  { value: 'Asia/Tokyo',          label: 'Tokyo (JST)',                  region: 'Asia' },
  { value: 'Asia/Seoul',          label: 'Seoul (KST)',                  region: 'Asia' },

  { value: 'Australia/Perth',     label: 'Perth (AWST)',                 region: 'Oceania' },
  { value: 'Australia/Sydney',    label: 'Sydney (AET)',                 region: 'Oceania' },
  { value: 'Pacific/Auckland',    label: 'Auckland (NZT)',               region: 'Oceania' },
];
