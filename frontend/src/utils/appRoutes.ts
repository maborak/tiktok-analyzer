/**
 * appRoutes.ts
 *
 * Centralized navigation path builder.
 * All UI route paths must be constructed through this helper so that
 * navigation is consistent across the application.
 *
 * Usage:
 *   import { routes } from '../../../utils/appRoutes';
 *   navigate({ to: routes.account.tickets });
 *   <Link to={routes.account.billing.invoiceDetail(invoice.id)} />
 */

export const routes = {
    home: '/',
    contact: '/contact',
    faq: '/help',

    account: {
        root: '/account',
        recipients: '/account/recipients',
        verifyRecipient: '/account/verify-recipient',
        verify: '/account/verify',
        resetPassword: '/account/reset-password',
        tickets: '/account/tickets',
        ticketDetail: (id: string | number) => `/account/tickets/${id}`,
        billing: {
            packages: '/account/billing/packages',
            checkout: '/account/billing/checkout',
            orders: '/account/billing/orders',
            success: '/account/billing/success',
            invoices: '/account/billing/invoices',
            invoiceDetail: (id: string | number) => `/account/billing/invoices/${id}`,
            creditHistory: '/account/billing/credit-history',
        },
    },

    admin: {
        users: '/admin/users',
        roles: '/admin/rbac/roles',
        permissions: '/admin/rbac/permissions',
        tickets: '/admin/tickets',
        ticketDetail: (id: string | number) => `/admin/tickets/${id}`,
        livechat: '/admin/livechat',
        billing: {
            packages: '/admin/billing/packages',
            paymentGateways: '/admin/billing/payment-gateways',
            pendingPayments: '/admin/billing/pending-payments',
        },
    },
} as const;
