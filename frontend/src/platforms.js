const PLATFORMS = {
  local: {
    label: "Local Backend",
    apiBaseUrl: "http://127.0.0.1:8000/api/v1",
  },
  drupal: {
    label: "Drupal Gateway",
    apiBaseUrl: "http://127.0.0.1:8080/api/v1",
  },
  staging: {
    label: "Staging",
    apiBaseUrl: "https://staging.example.com/api/v1",
  },
};

const STORAGE_KEY = "ai-paper-platform";

export function listPlatforms() {
  return Object.entries(PLATFORMS).map(([key, value]) => ({
    key,
    ...value,
  }));
}

export function getPlatformConfig() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return { platform: "local", ...PLATFORMS.local };
  try {
    return JSON.parse(saved);
  } catch {
    return { platform: "local", ...PLATFORMS.local };
  }
}

export function setPlatformConfig(platform, apiBaseUrl) {
  const base = PLATFORMS[platform] || PLATFORMS.local;
  const config = {
    platform,
    apiBaseUrl: apiBaseUrl || base.apiBaseUrl,
    label: base.label,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  return config;
}
