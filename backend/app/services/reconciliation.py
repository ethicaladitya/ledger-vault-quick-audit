from datetime import timedelta
from uuid import uuid4
from sqlalchemy.orm import Session
from ..models import Transaction, AuditEvent
NEUTRAL={"card_settlement","own_transfer"}
def reconcile(db: Session):
    txns=db.query(Transaction).filter(Transaction.match_group.is_(None)).all(); linked=0; ambiguous=0
    debits=[t for t in txns if t.debit>0 and t.category=="card_settlement"]
    credits=[t for t in txns if t.credit>0 and t.category=="card_settlement"]
    for debit in debits:
        candidates=[c for c in credits if c.credit==debit.debit and 0 <= (c.txn_date-debit.txn_date).days <= 7]
        if len(candidates)==1:
            gid=str(uuid4()); debit.match_group=candidates[0].match_group=gid; debit.status=candidates[0].status="confirmed_settlement"; linked+=1
        elif len(candidates)>1: debit.status="ambiguous"; ambiguous+=1
    db.add(AuditEvent(action="reconciled", detail=f"confirmed={linked}; ambiguous={ambiguous}")); db.commit()
    return {"confirmed":linked,"ambiguous":ambiguous}
