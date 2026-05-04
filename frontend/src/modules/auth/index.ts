import { AuthRepositoryImpl } from './services/authRepository';

export type { AuthUser, AuthTokens, AuthRepository, OAuthLinkData, OAuthResponse } from './types';
export { AuthModal } from './components/AuthModal';
export { LinkAccountModal } from './components/LinkAccountModal';

export const authRepository = new AuthRepositoryImpl();
