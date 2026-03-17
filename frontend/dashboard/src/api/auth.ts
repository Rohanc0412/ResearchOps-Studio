type AccessTokenGetter = () => string | null;
type UnauthorizedHandler = () => void;

let getAccessToken: AccessTokenGetter = () => null;
let onUnauthorized: UnauthorizedHandler = () => {
  window.location.assign("/login");
};

export function setAccessTokenGetter(fn: AccessTokenGetter): void {
  getAccessToken = fn;
}

export function setUnauthorizedHandler(fn: UnauthorizedHandler): void {
  onUnauthorized = fn;
}

export function accessToken(): string | null {
  return getAccessToken();
}

export function handleUnauthorized(): void {
  onUnauthorized();
}

