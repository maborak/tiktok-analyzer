import { UserRepositoryImpl } from './services/userRepository';
import { RecipientRepositoryImpl } from './services/recipientRepository';

export * from './types';
export { StatusBadge, PriorityBadge, STATUS_COLORS, STATUS_LABELS, ADMIN_STATUS_LABELS } from './components/tickets/TicketBadges';

export const userRepository = new UserRepositoryImpl();
export const recipientRepository = new RecipientRepositoryImpl();
