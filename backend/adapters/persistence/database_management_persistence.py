"""
Database management persistence adapter.

Provides seed, reset, and purge operations for the framework's
core data: RBAC roles/permissions and payment gateways.
"""

from typing import Dict
import logging

from adapters.persistence._base import BasePersistenceAdapter

logger = logging.getLogger(__name__)


class DatabaseManagementPersistenceAdapter(BasePersistenceAdapter):

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def seed_database(self) -> bool:
        """Seed the database with all default data."""
        logger.info("Seeding database with default data...")
        try:
            self._seed_rbac()
            self._seed_payment_gateways()
            logger.info("Database seeding completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error seeding database: {e}")
            return False

    def reset_database(self) -> bool:
        """Drop all tables, recreate them, and seed defaults."""
        try:
            from database import Base

            Base.metadata.drop_all(bind=self.engine)
            logger.info("Dropped all database tables")

            Base.metadata.create_all(bind=self.engine)
            logger.info("Created fresh database tables")

            self._seed_rbac()
            self._seed_payment_gateways()
            logger.info("Seeded all default data")

            logger.info("Database reset completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error resetting database: {e}")
            return False

    def purge_all_data(self) -> Dict[str, int]:
        """Purge all data from all tables while keeping schema intact."""
        session = self._get_session()
        try:
            from database import Base
            from sqlalchemy import inspect, text

            deleted_counts: Dict[str, int] = {}
            inspector = inspect(self.engine)
            table_names = inspector.get_table_names()

            # Disable FK checks for the duration of the purge
            dialect = self.engine.dialect.name
            if dialect == "postgresql":
                session.execute(text("SET session_replication_role = 'replica';"))
            elif dialect == "sqlite":
                session.execute(text("PRAGMA foreign_keys = OFF;"))

            for table_name in table_names:
                result = session.execute(text(f"DELETE FROM \"{table_name}\""))
                deleted_counts[table_name] = result.rowcount

            # Re-enable FK checks
            if dialect == "postgresql":
                session.execute(text("SET session_replication_role = 'origin';"))
            elif dialect == "sqlite":
                session.execute(text("PRAGMA foreign_keys = ON;"))

            session.commit()
            return deleted_counts
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Internal seeders
    # ------------------------------------------------------------------

    def _seed_rbac(self):
        """Seed RBAC roles and permissions."""
        session = self._get_session()
        try:
            from database.auth.rbac_models import Role, Permission
            from database.auth.rbac_service import RBACService
            from sqlalchemy import select, func

            rbac_service = RBACService(session)

            default_roles = [
                {"name": "user", "description": "Regular user role", "is_system": True},
                {"name": "moderator", "description": "Moderator role with elevated permissions", "is_system": True},
                {"name": "admin", "description": "Administrator role with full access", "is_system": True},
            ]

            role_map = {}
            roles_created = 0
            for role_data in default_roles:
                existing = rbac_service.get_role_by_name(role_data["name"])
                if existing:
                    role_map[role_data["name"]] = existing
                else:
                    role = rbac_service.create_role(
                        name=role_data["name"],
                        description=role_data["description"],
                        is_system=role_data["is_system"],
                    )
                    if role:
                        role_map[role_data["name"]] = role
                        roles_created += 1

            session.commit()
            if roles_created > 0:
                logger.info(f"Seeded {roles_created} roles")

            default_permissions = [
                {"name": "admin:read", "description": "Read access to admin resources", "category": "admin"},
                {"name": "admin:write", "description": "Write access to admin resources", "category": "admin"},
                {"name": "admin:users:read", "description": "View users", "category": "admin"},
                {"name": "admin:users:write", "description": "Manage users", "category": "admin"},
                {"name": "admin:permissions:read", "description": "View permissions", "category": "admin"},
                {"name": "admin:permissions:write", "description": "Manage permissions", "category": "admin"},
            ]

            permission_map = {}
            perms_created = 0
            for perm_data in default_permissions:
                existing = rbac_service.get_permission_by_name(perm_data["name"])
                if existing:
                    permission_map[perm_data["name"]] = existing
                else:
                    perm = rbac_service.create_permission(
                        name=perm_data["name"],
                        description=perm_data["description"],
                        category=perm_data["category"],
                    )
                    if perm:
                        permission_map[perm_data["name"]] = perm
                        perms_created += 1

            session.commit()
            if perms_created > 0:
                logger.info(f"Seeded {perms_created} permissions")

            role_permission_mappings = {
                "user": [],
                "moderator": [
                    "admin:read",
                ],
                "admin": [
                    "admin:read", "admin:write",
                    "admin:users:read", "admin:users:write",
                    "admin:permissions:read", "admin:permissions:write",
                ],
            }

            mappings_created = 0
            session.commit()

            for role_name, perm_names in role_permission_mappings.items():
                if role_name not in role_map:
                    continue
                role = role_map[role_name]

                for perm_name in perm_names:
                    if perm_name not in permission_map:
                        continue
                    perm = permission_map[perm_name]

                    max_retries = 2
                    for attempt in range(max_retries):
                        try:
                            existing_perms = rbac_service.get_role_permissions_by_id(role.id)
                            if perm_name not in existing_perms:
                                if rbac_service.assign_permission_to_role_by_id(role.id, perm.id):
                                    mappings_created += 1
                            break
                        except Exception as e:
                            error_str = str(e).lower()
                            if "transaction is aborted" in error_str or "infailedsqltransaction" in error_str:
                                if attempt < max_retries - 1:
                                    session.rollback()
                                    continue
                                else:
                                    logger.warning(f"Could not assign {perm_name} to {role_name} after {max_retries} attempts: {e}")
                                    session.rollback()
                                    break
                            else:
                                logger.warning(f"Could not assign {perm_name} to {role_name}: {e}")
                                try:
                                    session.rollback()
                                except Exception:
                                    pass
                                break

            try:
                session.commit()
            except Exception as e:
                logger.warning(f"Error committing role-permission mappings: {e}")
                session.rollback()

            if mappings_created > 0:
                logger.info(f"Seeded {mappings_created} role-permission mappings")
            else:
                from database.auth.rbac_models import role_permissions
                total_mappings = session.execute(
                    select(func.count()).select_from(role_permissions)
                ).scalar() or 0
                if total_mappings > 0:
                    logger.debug(f"RBAC already configured ({total_mappings} role-permission mappings)")

        except Exception as e:
            session.rollback()
            logger.error(f"Error seeding RBAC: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()

    def _seed_payment_gateways(self):
        """Seed default payment gateway configurations."""
        try:
            from database.billing.models import PaymentGatewayConfig
            session = self._get_session()
            try:
                if session.query(PaymentGatewayConfig).count() > 0:
                    return

                import json
                gateways = [
                    PaymentGatewayConfig(
                        provider="PAYPAL", display_name="PayPal",
                        mode="sandbox", is_enabled=False, config=json.dumps({}),
                    ),
                    PaymentGatewayConfig(
                        provider="STRIPE", display_name="Stripe",
                        mode="sandbox", is_enabled=False, config=json.dumps({}),
                    ),
                    PaymentGatewayConfig(
                        provider="BITCOIN", display_name="Bitcoin",
                        mode="live", is_enabled=False,
                        config=json.dumps({"wallet_address": "", "network": "mainnet", "confirmations_required": 1}),
                    ),
                    PaymentGatewayConfig(
                        provider="BANK_TRANSFER", display_name="Bank Transfer",
                        mode="live", is_enabled=False,
                        config=json.dumps({"bank_name": "", "account_number": "", "routing_number": "", "swift_code": "", "instructions": ""}),
                    ),
                ]
                for gw in gateways:
                    session.add(gw)
                session.commit()
                logger.info(f"Seeded {len(gateways)} payment gateways")
            except Exception as e:
                session.rollback()
                logger.error(f"Error seeding payment gateways: {e}")
            finally:
                session.close()
        except ImportError:
            logger.warning("PaymentGatewayConfig not available — skipping payment gateway seed")
