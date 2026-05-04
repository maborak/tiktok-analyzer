"""
Ticket and LiveChat persistence adapter.

Implements TicketPersistencePort — all ticket, ticket-message, ticket-category,
ticket-tag, ticket-attachment, and livechat session/message operations.

Extracted from adapters/database_persistence.py (methods at lines 7491–7951).
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import Session, joinedload

from ports.ticket_persistence import TicketPersistencePort
from adapters.persistence._base import BasePersistenceAdapter

# Domain entities (aliased exactly as in database_persistence.py)
from domain.entities.ticket_models import (
    Ticket as DistTicket,
    TicketMessage as DistTicketMessage,
    TicketCategoryDef as DistTicketCategoryDef,
    TicketInboundConfig as DistTicketInboundConfig,
    TicketStatus as DistTicketStatus,
    TicketPriority as DistTicketPriority,
    TicketTag as DistTicketTag,
    TicketAttachment as DistTicketAttachment,
    TicketOrigin as DistTicketOrigin,
    LiveChatSession as DistLiveChatSession,
    LiveChatMessage as DistLiveChatMessage,
    LiveChatStatus as DistLiveChatStatus,
    LiveChatSenderType as DistLiveChatSenderType,
    LiveChatAttachment as DistLiveChatAttachment,
)

# Database models
from database.tickets.models import (
    TicketModel,
    TicketMessageModel,
    TicketCategoryModel,
    TicketTagModel,
    TicketTagAssociationModel,
    TicketAttachmentModel,
    TicketInboundConfigModel,
    LiveChatSessionModel,
    LiveChatMessageModel,
    LiveChatAttachmentModel,
)


class DatabaseTicketPersistenceAdapter(BasePersistenceAdapter, TicketPersistencePort):
    """Implements TicketPersistencePort — ticket and livechat persistence operations."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ticket_model_to_domain(self, t: TicketModel) -> DistTicket:
        return DistTicket(
            id=t.id,
            user_id=t.user_id,
            subject=t.subject,
            status=DistTicketStatus(t.status),
            priority=DistTicketPriority(t.priority),
            category_id=t.category_id,
            origin=DistTicketOrigin(t.origin),
            sender_email=t.sender_email,
            assigned_agent_id=t.assigned_agent_id,
            sla_due_date=t.sla_due_date,
            created_at=t.created_at,
            updated_at=t.updated_at,
            resolved_at=t.resolved_at,
            guest_access_token=t.guest_access_token,
            reopen_count=getattr(t, 'reopen_count', 0) or 0,
            tags=[DistTicketTag(id=tag.id, name=tag.name, color=tag.color) for tag in t.tags]
        )

    # ------------------------------------------------------------------
    # Ticket CRUD
    # ------------------------------------------------------------------

    def create_ticket(self, ticket: DistTicket, initial_message: DistTicketMessage) -> str:
        def _create(session: Session):
            db_ticket = TicketModel(
                id=ticket.id,
                user_id=ticket.user_id,
                subject=ticket.subject,
                status=ticket.status.value,
                priority=ticket.priority.value,
                category_id=ticket.category_id,
                origin=ticket.origin.value,
                sender_email=ticket.sender_email,
                assigned_agent_id=ticket.assigned_agent_id,
                sla_due_date=ticket.sla_due_date,
                guest_access_token=ticket.guest_access_token,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at
            )
            session.add(db_ticket)

            db_message = TicketMessageModel(
                id=initial_message.id,
                ticket_id=ticket.id,
                message=initial_message.message,
                sender_id=initial_message.sender_id,
                sender_email=initial_message.sender_email,
                is_internal_note=initial_message.is_internal_note,
                created_at=initial_message.created_at
            )
            session.add(db_message)

            for attachment in initial_message.attachments:
                db_attachment = TicketAttachmentModel(
                    id=attachment.id,
                    ticket_id=ticket.id,
                    message_id=initial_message.id,
                    file_name=attachment.file_name,
                    file_url=attachment.file_url,
                    content_type=attachment.content_type,
                    file_size=attachment.file_size,
                    created_at=attachment.created_at
                )
                session.add(db_attachment)

            return db_ticket.id
        return self._execute_with_retry(_create)

    def get_user_tickets(self, user_id: int, status: Optional[DistTicketStatus] = None, search: Optional[str] = None, page: int = 1, page_size: int = 20) -> dict:
        def _get(session: Session):
            query = session.query(TicketModel).options(joinedload(TicketModel.tags)).filter(TicketModel.user_id == user_id)
            if status:
                query = query.filter(TicketModel.status == status.value)
            if search:
                query = query.filter(TicketModel.subject.ilike(f"%{search}%"))
            total = query.count()
            offset = (page - 1) * page_size
            tickets = query.order_by(TicketModel.updated_at.desc()).offset(offset).limit(page_size).all()
            return {
                "items": [self._ticket_model_to_domain(t) for t in tickets],
                "total": total,
                "page": page,
                "page_size": page_size
            }
        return self._execute_with_retry(_get)

    def get_all_tickets(self, status: Optional[DistTicketStatus] = None, agent_id: Optional[int] = None, unassigned: bool = False, page: int = 1, page_size: int = 20) -> dict:
        def _get(session: Session):
            query = session.query(TicketModel).options(joinedload(TicketModel.tags))
            if status:
                query = query.filter(TicketModel.status == status.value)
            if agent_id:
                query = query.filter(TicketModel.assigned_agent_id == agent_id)
            if unassigned:
                query = query.filter(TicketModel.assigned_agent_id == None)
            total = query.count()
            offset = (page - 1) * page_size
            tickets = query.order_by(TicketModel.updated_at.desc()).offset(offset).limit(page_size).all()
            return {
                "items": [self._ticket_model_to_domain(t) for t in tickets],
                "total": total,
                "page": page,
                "page_size": page_size
            }
        return self._execute_with_retry(_get)

    def get_ticket(self, ticket_id: str) -> Optional[DistTicket]:
        def _get(session: Session):
            t = session.query(TicketModel).options(joinedload(TicketModel.tags)).filter(TicketModel.id == ticket_id).first()
            if not t:
                return None
            return self._ticket_model_to_domain(t)
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Ticket messages
    # ------------------------------------------------------------------

    def add_ticket_message(self, message: DistTicketMessage) -> str:
        def _add(session: Session):
            db_message = TicketMessageModel(
                id=message.id,
                ticket_id=message.ticket_id,
                message=message.message,
                sender_id=message.sender_id,
                sender_email=message.sender_email,
                is_internal_note=message.is_internal_note,
                created_at=message.created_at
            )
            session.add(db_message)

            # Auto-update ticket timestamp
            t = session.query(TicketModel).filter(TicketModel.id == message.ticket_id).first()
            if t:
                t.updated_at = message.created_at

            for attach in message.attachments:
                db_attach = TicketAttachmentModel(
                    id=attach.id,
                    ticket_id=message.ticket_id,
                    message_id=message.id,
                    file_name=attach.file_name,
                    file_url=attach.file_url,
                    content_type=attach.content_type,
                    file_size=attach.file_size,
                    created_at=attach.created_at
                )
                session.add(db_attach)
            return db_message.id
        return self._execute_with_retry(_add)

    def get_ticket_messages(self, ticket_id: str) -> List[DistTicketMessage]:
        def _get(session: Session):
            messages = session.query(TicketMessageModel).options(joinedload(TicketMessageModel.attachments)).filter(TicketMessageModel.ticket_id == ticket_id).order_by(TicketMessageModel.created_at.asc()).all()
            return [
                DistTicketMessage(
                    id=m.id,
                    ticket_id=m.ticket_id,
                    message=m.message,
                    created_at=m.created_at,
                    sender_id=m.sender_id,
                    sender_email=m.sender_email,
                    is_internal_note=m.is_internal_note,
                    attachments=[
                        DistTicketAttachment(
                            id=a.id, ticket_id=a.ticket_id, message_id=a.message_id,
                            file_name=a.file_name, file_url=a.file_url,
                            content_type=a.content_type, file_size=a.file_size, created_at=a.created_at
                        ) for a in m.attachments
                    ]
                ) for m in messages
            ]
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Ticket status / priority / assignment
    # ------------------------------------------------------------------

    def update_ticket_status(self, ticket_id: str, status: DistTicketStatus) -> bool:
        def _update(session: Session):
            t = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if not t: return False
            t.status = status.value
            t.updated_at = datetime.now(timezone.utc)
            if status in [DistTicketStatus.RESOLVED, DistTicketStatus.CLOSED]:
                t.resolved_at = datetime.now(timezone.utc)
            return True
        return self._execute_with_retry(_update)

    def reopen_ticket(self, ticket_id: str) -> bool:
        def _reopen(session: Session):
            t = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if not t:
                return False
            t.status = DistTicketStatus.OPEN.value
            t.resolved_at = None
            t.reopen_count = (t.reopen_count or 0) + 1
            t.updated_at = datetime.now(timezone.utc)
            return True
        return self._execute_with_retry(_reopen)

    def update_ticket_priority(self, ticket_id: str, priority: DistTicketPriority) -> bool:
        def _update(session: Session):
            t = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if not t: return False
            t.priority = priority.value
            t.updated_at = datetime.now(timezone.utc)
            return True
        return self._execute_with_retry(_update)

    def assign_ticket(self, ticket_id: str, agent_id: Optional[int]) -> bool:
        def _assign(session: Session):
            t = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if not t: return False
            # Convert 0 or falsy values to None for unassignment (NULL in database)
            t.assigned_agent_id = agent_id if agent_id and agent_id > 0 else None
            t.updated_at = datetime.now(timezone.utc)
            return True
        return self._execute_with_retry(_assign)

    # ------------------------------------------------------------------
    # Ticket categories
    # ------------------------------------------------------------------

    def create_ticket_category(self, category: DistTicketCategoryDef) -> str:
        def _create(session: Session):
            db_category = TicketCategoryModel(
                id=category.id,
                name=category.name,
                description=category.description,
                is_active=category.is_active
            )
            session.add(db_category)
            return db_category.id
        return self._execute_with_retry(_create)

    def update_ticket_category(self, category_id: str, name: Optional[str] = None, description: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        def _update(session: Session):
            c = session.query(TicketCategoryModel).filter(TicketCategoryModel.id == category_id).first()
            if not c: return False
            if name is not None: c.name = name
            if description is not None: c.description = description
            if is_active is not None: c.is_active = is_active
            return True
        return self._execute_with_retry(_update)

    def get_ticket_categories(self, active_only: bool = True) -> List[DistTicketCategoryDef]:
        def _get(session: Session):
            query = session.query(TicketCategoryModel)
            if active_only:
                query = query.filter(TicketCategoryModel.is_active == True)
            categories = query.all()
            return [
                DistTicketCategoryDef(
                    id=c.id, name=c.name, description=c.description, is_active=c.is_active
                ) for c in categories
            ]
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Guest ticket migration
    # ------------------------------------------------------------------

    def migrate_guest_tickets(self, email: str, user_id: int) -> int:
        def _migrate(session: Session):
            result = session.query(TicketModel).filter(
                TicketModel.sender_email == email,
                TicketModel.user_id == None
            ).update({"user_id": user_id}, synchronize_session=False)
            return result
        return self._execute_with_retry(_migrate)

    # ------------------------------------------------------------------
    # Inbound config
    # ------------------------------------------------------------------

    def get_inbound_config(self, email_address: str) -> Optional[DistTicketInboundConfig]:
        def _get(session: Session):
            c = session.query(TicketInboundConfigModel).filter(TicketInboundConfigModel.email_address == email_address).first()
            if not c: return None
            return DistTicketInboundConfig(id=c.id, email_address=c.email_address, default_category_id=c.default_category_id)
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Ticket tags
    # ------------------------------------------------------------------

    def add_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        def _add(session: Session):
            assoc = TicketTagAssociationModel(ticket_id=ticket_id, tag_id=tag_id)
            session.merge(assoc)
            return True
        return self._execute_with_retry(_add)

    def remove_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        def _rm(session: Session):
            session.query(TicketTagAssociationModel).filter(
                TicketTagAssociationModel.ticket_id == ticket_id,
                TicketTagAssociationModel.tag_id == tag_id
            ).delete()
            return True
        return self._execute_with_retry(_rm)

    # ------------------------------------------------------------------
    # Ticket attachments
    # ------------------------------------------------------------------

    def add_ticket_attachment(self, attachment: DistTicketAttachment) -> str:
        def _save(session: Session):
            db_attach = TicketAttachmentModel(
                id=attachment.id,
                ticket_id=attachment.ticket_id,
                message_id=attachment.message_id,
                file_name=attachment.file_name,
                file_url=attachment.file_url,
                content_type=attachment.content_type,
                file_size=attachment.file_size,
                created_at=attachment.created_at
            )
            session.add(db_attach)
            return db_attach.id
        return self._execute_with_retry(_save)

    def get_ticket_message_summaries(self, ticket_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not ticket_ids:
            return {}

        def _query(session: Session):
            # Join messages with tickets to determine agent replies
            # (agent = sender_id differs from ticket.user_id)
            # Detect agent replies with NULL-safe logic:
            # - sender_id must be non-NULL (guest/email messages have no sender_id)
            # - For user tickets (user_id not NULL): agent if sender_id != user_id
            # - For guest tickets (user_id is NULL): any message with sender_id is from an agent
            is_agent_reply = and_(
                TicketMessageModel.sender_id.isnot(None),
                or_(
                    TicketModel.user_id.is_(None),
                    TicketMessageModel.sender_id != TicketModel.user_id,
                ),
            )
            rows = (
                session.query(
                    TicketMessageModel.ticket_id,
                    func.count(TicketMessageModel.id).label("reply_count"),
                    func.max(TicketMessageModel.created_at).label("last_message_at"),
                    func.max(
                        case(
                            (is_agent_reply, TicketMessageModel.created_at),
                            else_=None,
                        )
                    ).label("last_agent_message_at"),
                )
                .join(TicketModel, TicketMessageModel.ticket_id == TicketModel.id)
                .filter(TicketMessageModel.ticket_id.in_(ticket_ids))
                .group_by(TicketMessageModel.ticket_id)
                .all()
            )
            return {
                r.ticket_id: {
                    "reply_count": r.reply_count,
                    "last_message_at": r.last_message_at,
                    "last_agent_message_at": r.last_agent_message_at,
                }
                for r in rows
            }
        return self._execute_with_retry(_query)

    # ==================================================================
    # LiveChat Methods
    # ==================================================================

    def create_chat_session(self, session: DistLiveChatSession) -> str:
        def _create(db_session: Session):
            db_model = LiveChatSessionModel(
                id=session.id,
                user_id=session.user_id,
                session_token=session.session_token,
                status=session.status.value,
                created_at=session.created_at,
                agent_id=session.agent_id,
                ticket_id=session.ticket_id,
                is_authenticated_user=session.is_authenticated_user,
                ip_address=session.ip_address,
                user_agent=session.user_agent,
                current_url=session.current_url,
                initial_context=session.initial_context,
                initial_message=session.initial_message,
                is_proactive=session.is_proactive
            )
            db_session.add(db_model)
            return db_model.id
        return self._execute_with_retry(_create)

    def get_chat_session(self, session_id: str) -> Optional[DistLiveChatSession]:
        def _get(db_session: Session):
            s = db_session.query(LiveChatSessionModel).filter(LiveChatSessionModel.id == session_id).first()
            if not s: return None
            return DistLiveChatSession(
                id=s.id, user_id=s.user_id, session_token=s.session_token,
                status=DistLiveChatStatus(s.status), created_at=s.created_at, ended_at=s.ended_at,
                agent_id=s.agent_id, ticket_id=s.ticket_id, is_authenticated_user=s.is_authenticated_user,
                ip_address=s.ip_address, user_agent=s.user_agent, current_url=s.current_url,
                initial_context=s.initial_context, initial_message=s.initial_message,
                typing_status=s.typing_status, first_response_at=s.first_response_at,
                resolution_time_seconds=s.resolution_time_seconds, csat_score=s.csat_score,
                csat_comment=s.csat_comment, is_proactive=s.is_proactive
            )
        return self._execute_with_retry(_get)

    def add_chat_message(self, message: DistLiveChatMessage) -> str:
        def _add(db_session: Session):
            db_message = LiveChatMessageModel(
                id=message.id,
                session_id=message.session_id,
                sender_type=message.sender_type.value,
                sender_id=message.sender_id,
                message=message.message,
                created_at=message.created_at,
                context=message.context
            )
            db_session.add(db_message)
            return db_message.id
        return self._execute_with_retry(_add)

    def get_chat_messages(self, session_id: str) -> List[DistLiveChatMessage]:
        def _get(db_session: Session):
            messages = db_session.query(LiveChatMessageModel).options(
                joinedload(LiveChatMessageModel.attachments)
            ).filter(
                LiveChatMessageModel.session_id == session_id
            ).order_by(LiveChatMessageModel.created_at.asc()).all()
            return [
                DistLiveChatMessage(
                    id=m.id,
                    session_id=m.session_id,
                    sender_type=DistLiveChatSenderType(m.sender_type),
                    sender_id=m.sender_id,
                    message=m.message,
                    created_at=m.created_at,
                    attachments=[
                        DistLiveChatAttachment(
                            id=a.id,
                            session_id=a.session_id,
                            message_id=a.message_id,
                            file_name=a.file_name,
                            file_url=a.file_url,
                            content_type=a.content_type,
                            file_size=a.file_size,
                            created_at=a.created_at
                        ) for a in m.attachments
                    ],
                    context=m.context,
                    read_at=m.read_at
                ) for m in messages
            ]
        return self._execute_with_retry(_get)

    def get_active_chat_sessions(self, status: Optional[DistLiveChatStatus] = None, page: int = 1, page_size: int = 20) -> dict:
        def _get(db_session: Session):
            query = db_session.query(LiveChatSessionModel)
            if status:
                query = query.filter(LiveChatSessionModel.status == status.value)
            # If no status specified, return all sessions (no filter applied)
            total = query.count()
            offset = (page - 1) * page_size
            sessions = query.order_by(LiveChatSessionModel.created_at.desc()).offset(offset).limit(page_size).all()
            items = [
                DistLiveChatSession(
                    id=s.id, user_id=s.user_id, session_token=s.session_token,
                    status=DistLiveChatStatus(s.status), created_at=s.created_at, ended_at=s.ended_at,
                    agent_id=s.agent_id, ticket_id=s.ticket_id, is_authenticated_user=s.is_authenticated_user,
                    ip_address=s.ip_address, user_agent=s.user_agent, current_url=s.current_url,
                    initial_context=s.initial_context, initial_message=s.initial_message,
                    typing_status=s.typing_status, first_response_at=s.first_response_at,
                    resolution_time_seconds=s.resolution_time_seconds, csat_score=s.csat_score,
                    csat_comment=s.csat_comment, is_proactive=s.is_proactive
                ) for s in sessions
            ]
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size
            }
        return self._execute_with_retry(_get)

    def get_livechat_session_stats(self) -> Dict[str, int]:
        def _get_stats(db_session: Session):
            from sqlalchemy import func
            # Get counts by status
            status_counts = db_session.query(
                LiveChatSessionModel.status,
                func.count(LiveChatSessionModel.id)
            ).group_by(LiveChatSessionModel.status).all()

            # Initialize with zeros
            stats = {
                "waiting": 0,
                "active": 0,
                "ended": 0,
                "total": 0
            }

            # Map status values to keys
            for status, count in status_counts:
                stats[status.lower()] = count
                stats["total"] += count

            return stats
        return self._execute_with_retry(_get_stats)

    def update_chat_session_activity(self, session_id: str, current_url: Optional[str] = None, typing_status: Optional[dict] = None) -> bool:
        def _update(db_session: Session):
            s = db_session.query(LiveChatSessionModel).filter(LiveChatSessionModel.id == session_id).first()
            if not s:
                return False
            if current_url:
                s.current_url = current_url
            if typing_status is not None:
                s.typing_status = typing_status
            return True
        return self._execute_with_retry(_update)

    def update_chat_session_status(self, session_id: str, status: DistLiveChatStatus, ticket_id: Optional[str] = None, agent_id: Optional[int] = None) -> bool:
        def _update(db_session: Session):
            s = db_session.query(LiveChatSessionModel).filter(LiveChatSessionModel.id == session_id).first()
            if not s: return False
            s.status = status.value
            if status == DistLiveChatStatus.ENDED:
                s.ended_at = datetime.now(timezone.utc)
            if ticket_id:
                s.ticket_id = ticket_id
            if agent_id:
                s.agent_id = agent_id
            return True
        return self._execute_with_retry(_update)

    def add_livechat_attachment(self, attachment: Any) -> str:
        def _add(db_session: Session):
            db_attach = LiveChatAttachmentModel(
                id=attachment.id,
                session_id=attachment.session_id,
                message_id=attachment.message_id,
                file_name=attachment.file_name,
                file_url=attachment.file_url,
                content_type=attachment.content_type,
                file_size=attachment.file_size,
                created_at=attachment.created_at
            )
            db_session.add(db_attach)
            return db_attach.id
        return self._execute_with_retry(_add)

    def get_livechat_attachment_by_file_url(self, file_url: str) -> Optional[Any]:
        def _get(db_session: Session):
            row = db_session.query(LiveChatAttachmentModel).filter(
                LiveChatAttachmentModel.file_url == file_url
            ).first()
            if not row:
                return None
            return DistLiveChatAttachment(
                id=row.id,
                session_id=row.session_id,
                message_id=row.message_id,
                file_name=row.file_name,
                file_url=row.file_url,
                content_type=row.content_type,
                file_size=row.file_size,
                created_at=row.created_at,
            )
        return self._execute_with_retry(_get)
