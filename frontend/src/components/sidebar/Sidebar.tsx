import { useState, useEffect, useCallback } from 'react';
import { Link, useMatchRoute } from '@tanstack/react-router';
import {
  Scale, X, Home, LogOut, User, Shield,
  ChevronRight, Ticket, Headset,
  MessageSquare, FileText, Receipt, Settings, Settings2,
  Lock, KeyRound, UserPlus, History, Coins,
  Layers, LogIn,
  Database, ShieldAlert, Radio, BarChart3, Gift,
} from 'lucide-react';
import { cn } from '../../utils/cn';
import { appConfig } from '../../config/env';
import { AuthModal } from '@auth';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

// -- Types --

interface NavigationItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  locked?: boolean;
}

interface NavigationSection {
  title: string;
  key: string;
  items: NavigationItem[];
  collapsible?: boolean;
  defaultExpanded?: boolean;
}

// -- Navigation Data --

const generalSection: NavigationSection = {
  title: 'General',
  key: 'general',
  items: [
    { name: 'Home', href: '/admin', icon: Home, end: true },
  ],
};

const adminPlatformSection: NavigationSection = {
  title: 'Platform',
  key: 'admin-platform',
  collapsible: true,
  defaultExpanded: true,
  items: [
    { name: 'Users', href: `/admin/users`, icon: User },
    { name: 'Roles', href: `/admin/rbac/roles`, icon: Shield },
    { name: 'Permissions', href: `/admin/rbac/permissions`, icon: KeyRound },
  ],
};

const adminSecuritySection: NavigationSection = {
  title: 'Security',
  key: 'admin-security',
  collapsible: true,
  defaultExpanded: true,
  items: [
    { name: 'Account Lockouts', href: `/admin/security/lockouts`, icon: ShieldAlert },
  ],
};

const adminMonitoringSection: NavigationSection = {
  title: 'Monitoring',
  key: 'admin-monitoring',
  collapsible: true,
  defaultExpanded: true,
  items: [
    { name: 'Event Monitor', href: `/admin/monitoring/events`, icon: FileText },
  ],
};

const adminRevenueSection: NavigationSection = {
  title: 'Revenue',
  key: 'admin-revenue',
  collapsible: true,
  defaultExpanded: false,
  items: [
    { name: 'Packages', href: `/admin/billing/packages`, icon: Layers },
    { name: 'Payment Gateways', href: `/admin/billing/payment-gateways`, icon: Settings },
    { name: 'Pending Payments', href: `/admin/billing/pending-payments`, icon: Receipt },
  ],
};

const adminSettingsSection: NavigationSection = {
  title: 'Settings',
  key: 'admin-settings',
  collapsible: true,
  defaultExpanded: false,
  items: [
    { name: 'Configuration', href: `/admin/settings/configuration`, icon: Settings2 },
    { name: 'App Settings', href: `/admin/settings/config`, icon: Database },
  ],
};

const adminSupportSection: NavigationSection = {
  title: 'Admin Support',
  key: 'admin-support',
  collapsible: true,
  defaultExpanded: false,
  items: [
    { name: 'Support Tickets', href: `/admin/tickets`, icon: Headset },
    { name: 'Live Chat Queue', href: `/admin/livechat`, icon: MessageSquare },
  ],
};

const adminTikTokSection: NavigationSection = {
  title: 'TikTok',
  key: 'admin-tiktok',
  collapsible: true,
  defaultExpanded: true,
  items: [
    { name: 'Dashboard',   href: `/admin/tiktok/dashboard`,   icon: BarChart3 },
    { name: 'Lives',       href: `/admin/tiktok`,             icon: Radio, end: true },
    { name: 'History',     href: `/admin/tiktok/history`,     icon: History },
    { name: 'Gifts',       href: `/admin/tiktok/gifts`,       icon: Gift },
    // Settings consolidates every TikTok-related config + ops
    // surface under one sidebar entry:
    //   - General      → typed-config grouped editor (mirrors the
    //                    `tiktok` namespace on /admin/settings/configuration).
    //   - Sign Engine  → the rich provider-switching UI (was a
    //                    separate sidebar entry; now a sub-tab).
    //   - Worker       → listener-pool status (was a tab inside
    //                    /admin/tiktok; now a sub-tab here).
    // The legacy /admin/tiktok/sign-config route still works for
    // direct-URL access / bookmarks but isn't surfaced in the nav.
    { name: 'Settings',    href: `/admin/tiktok/settings`,    icon: Settings },
  ],
};

const userSection: NavigationSection = {
  title: 'Account',
  key: 'user-section',
  items: [
    { name: 'My Account', href: '/account', icon: User, end: true },
    { name: 'Recipients', href: `/account/recipients`, icon: UserPlus },
  ],
};

const billingSection: NavigationSection = {
  title: 'Billing',
  key: 'billing',
  collapsible: true,
  defaultExpanded: true,
  items: [
    { name: 'Buy Credits', href: `/account/billing/packages`, icon: Coins },
    { name: 'Orders', href: `/account/billing/orders`, icon: FileText },
    { name: 'Invoices', href: `/account/billing/invoices`, icon: Receipt },
    { name: 'Credit History', href: `/account/billing/credit-history`, icon: History },
  ],
};

const supportSection: NavigationSection = {
  title: 'Support',
  key: 'support',
  items: [
    { name: 'Support Tickets', href: `/account/tickets`, icon: Ticket },
  ],
};

// -- Collapse State --

const COLLAPSE_STORAGE_KEY = 'sidebar_collapsed';

function useCollapsedSections() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      const stored = localStorage.getItem(COLLAPSE_STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch { return {}; }
  });

  const toggle = useCallback((key: string) => {
    setCollapsed(prev => {
      const next = { ...prev, [key]: !prev[key] };
      localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const isCollapsed = useCallback((section: NavigationSection) => {
    if (!section.collapsible) return false;
    if (collapsed[section.key] !== undefined) return collapsed[section.key];
    return !section.defaultExpanded;
  }, [collapsed]);

  return { isCollapsed, toggle };
}

// -- NavItem Component (replaces NavLink from react-router-dom) --

function NavItem({ item, onClick }: { item: NavigationItem; onClick?: () => void }) {
  const matchRoute = useMatchRoute();
  const isActive = !!matchRoute({ to: item.href, fuzzy: !item.end });
  return (
    <Link
      to={item.href}
      onClick={onClick}
      className={cn('nav-link', isActive && 'active')}
    >
      <span style={{ color: isActive ? 'var(--color-sidebar-text-active)' : 'var(--color-sidebar-text)' }}>
        <item.icon className="h-4 w-4" />
      </span>
      <span className="flex-1">{item.name}</span>
    </Link>
  );
}

// -- NavSection Component --

interface NavSectionProps {
  section: NavigationSection;
  onItemClick?: () => void;
  onLockedClick?: () => void;
  renderAfter?: React.ReactNode;
  isCollapsed: boolean;
  onToggleCollapse?: () => void;
}

function NavSection({ section, onItemClick, onLockedClick, renderAfter, isCollapsed, onToggleCollapse }: NavSectionProps) {
  return (
    <div className="mb-5">
      <button
        type="button"
        onClick={section.collapsible ? onToggleCollapse : undefined}
        className={cn(
          'nav-section-header w-full flex items-center justify-between',
          section.collapsible && 'cursor-pointer'
        )}
      >
        <span>{section.title}</span>
        {section.collapsible && (
          <ChevronRight className={cn(
            'h-3 w-3 transition-transform duration-200',
            !isCollapsed && 'rotate-90'
          )} />
        )}
      </button>
      <div className={cn(
        'space-y-0.5 overflow-hidden transition-all duration-200',
        isCollapsed ? 'max-h-0 opacity-0' : 'max-h-[500px] opacity-100'
      )}>
        {section.items.map((item) =>
          item.locked ? (
            <button
              key={item.name}
              type="button"
              onClick={() => {
                onLockedClick?.();
                onItemClick?.();
              }}
              className="nav-link opacity-40 w-full text-left"
            >
              <item.icon className="h-4 w-4" />
              <span className="flex-1">{item.name}</span>
              <Lock className="h-3 w-3" />
            </button>
          ) : (
            <NavItem
              key={item.name}
              item={item}
              onClick={onItemClick}
            />
          )
        )}
        {renderAfter}
      </div>
    </div>
  );
}

// -- Sidebar Props --

interface SidebarProps {
  isAuthenticated: boolean;
  isAdmin: boolean;
  isImpersonating: boolean;
  onLogout: () => void;
  onStopImpersonation: () => void;
  isMobile?: boolean;
  isOpen?: boolean;
  onClose?: () => void;
}

// -- Sidebar Component --

export function Sidebar({
  isAuthenticated,
  isAdmin,
  isImpersonating,
  onLogout,
  onStopImpersonation,
  isMobile = false,
  isOpen = true,
  onClose,
}: SidebarProps) {
  const { isCollapsed, toggle } = useCollapsedSections();
  const [showAuthModal, setShowAuthModal] = useState(false);
  const handleItemClick = isMobile ? onClose : undefined;

  useEffect(() => {
    if (!isMobile || !isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isMobile, isOpen, onClose]);

  const renderSection = (section: NavigationSection, renderAfter?: React.ReactNode) => (
    <NavSection
      key={section.key}
      section={section}
      onItemClick={handleItemClick}
      onLockedClick={() => setShowAuthModal(true)}
      renderAfter={renderAfter}
      isCollapsed={isCollapsed(section)}
      onToggleCollapse={() => toggle(section.key)}
    />
  );

  const logoutButton = (
    <button
      onClick={() => {
        handleItemClick?.();
        if (isImpersonating) onStopImpersonation();
        else onLogout();
      }}
      className="nav-link w-full text-left hover:text-error-500"
    >
      <LogOut className="h-4 w-4" />
      <span className="flex-1">{isImpersonating ? 'Stop Impersonation' : 'Sign Out'}</span>
    </button>
  );

  const navContent = (
    <>
      {renderSection(generalSection)}

      {isAdmin && appConfig.mode !== 'client' && (
        <>
          {renderSection(adminPlatformSection)}
          {renderSection(adminSecuritySection)}
          {renderSection(adminMonitoringSection)}
          {renderSection(adminRevenueSection)}
          {renderSection(adminSettingsSection)}
          {renderSection(adminSupportSection)}
          {renderSection(adminTikTokSection)}
        </>
      )}

      {isAuthenticated && (
        <>
          {renderSection(userSection, logoutButton)}
          {renderSection(billingSection)}
          {renderSection(supportSection)}
        </>
      )}

    </>
  );

  const header = (
    <div className="flex items-center min-w-0">
      <div className="flex-shrink-0 p-1.5 rounded-lg" style={{ backgroundColor: 'var(--color-sidebar-logo-bg)' }}>
        <Scale className="h-5 w-5" style={{ color: '#ffffff' }} />
      </div>
      <span className="ml-3 text-base font-semibold truncate" style={{ color: 'var(--color-sidebar-logo-text)' }}>{appConfig.name}</span>
    </div>
  );

  const themeToggleRow = (
    <div
      className="flex-shrink-0 px-3 py-2 flex items-center justify-between"
      style={{ borderTop: '1px solid var(--color-sidebar-divider)' }}
    >
      <ThemeToggle />
      <span
        className="text-[9px] tabular-nums"
        style={{ color: 'var(--color-sidebar-text)', opacity: 0.5 }}
      >
        v{appConfig.version}
      </span>
    </div>
  );

  const footer = !isAuthenticated ? (
    <>
      <div className="flex-shrink-0 p-3" style={{ borderTop: '1px solid var(--color-sidebar-divider)' }}>
        <button
          type="button"
          onClick={() => {
            setShowAuthModal(true);
            handleItemClick?.();
          }}
          className="btn-primary w-full justify-center"
        >
          <LogIn className="h-4 w-4" />
          Sign In / Register
        </button>
      </div>
      {themeToggleRow}
    </>
  ) : (
    themeToggleRow
  );

  const authModal = !isAuthenticated && (
    <AuthModal
      isOpen={showAuthModal}
      onClose={() => setShowAuthModal(false)}
      initialView="login"
      onSuccess={() => setShowAuthModal(false)}
      notice="Sign in or create a free account to get started."
    />
  );

  // -- Mobile --

  if (isMobile) {
    return (
      <>
        <div className={cn('fixed inset-0 z-50 lg:hidden', isOpen ? 'block' : 'hidden')}>
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-sm"
            onClick={onClose}
            role="button"
            aria-label="Close navigation"
          />
          <div
            className="relative flex w-full max-w-[280px] h-full flex-col shadow-xl"
            style={{ backgroundColor: 'var(--color-sidebar-bg)' }}
          >
            <div
              className="flex h-14 flex-shrink-0 items-center justify-between px-4"
              style={{ borderBottom: '1px solid var(--color-sidebar-divider)' }}
            >
              {header}
              <button
                onClick={onClose}
                className="p-1.5 rounded-md transition-colors"
                style={{ color: 'var(--color-sidebar-text)', backgroundColor: 'transparent' }}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto px-3 py-4 min-h-0 scrollbar-hide">
              {navContent}
            </nav>
            {footer}
          </div>
        </div>
        {authModal}
      </>
    );
  }

  // -- Desktop --

  return (
    <>
      <div className="hidden lg:flex lg:w-64 lg:flex-col lg:fixed lg:inset-y-0">
        <div className="sidebar flex flex-col h-screen">
          <div
            className="flex items-center h-14 flex-shrink-0 px-5"
            style={{ borderBottom: '1px solid var(--color-sidebar-divider)' }}
          >
            {header}
          </div>
          <nav className="flex-1 overflow-y-auto px-3 py-4 min-h-0 scrollbar-hide">
            {navContent}
          </nav>
          {footer}
        </div>
      </div>
      {authModal}
    </>
  );
}
