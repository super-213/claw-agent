"""Activity-owned durable outbox using authenticated chat push device transport."""
import json
import time
import uuid


def deliver_activity_notifications(service, transport):
    service.cleanup_expired()
    now = time.time()
    # Subscriptions and auth belong to the existing push service, not the activity.
    with transport.store.db() as db:
        devices = [dict(row) for row in db.execute('SELECT * FROM chat_devices WHERE enabled=1')]
    members = {m['member_id']: m for m in service.members.list() if m['status'] == 'active'}
    for device in devices:
        if not transport.auth_valid(device['auth_hash'], device['user_id']):
            continue
        with service.store.transaction() as doc:
            candidates = [e['id'] for e in doc['notifications'].values() if not e['read_at']
                          and e['status'] != 'cancelled' and members.get(e['member_id'], {}).get('user_id') == device['user_id']]
        for event_id in candidates:
            token = uuid.uuid4().hex
            with service.store.transaction() as doc:
                event = next((e for e in doc['notifications'].values() if e['id'] == event_id), None)
                if not event or event['read_at'] or event['status'] == 'cancelled':
                    continue
                delivery = event.setdefault('deliveries', {}).setdefault(device['id'], dict(state='pending', attempts=0, next_at=0))
                if delivery['state'] in ('sent', 'failed') or delivery['next_at'] > now:
                    continue
                delivery.update(state='sending', token=token, next_at=now + 60, attempts=delivery['attempts'] + 1)
                identifier = event['activity_id']
            # No file lock during network work. Recheck revocation immediately before send.
            try:
                with transport.store.db() as db:
                    current = db.execute('SELECT * FROM chat_devices WHERE id=?', (device['id'],)).fetchone()
                with service.store.transaction() as doc:
                    live = identifier in doc['activities'] and any(e['id'] == event_id and not e['read_at'] for e in doc['notifications'].values())
                if not live or not current or not current['enabled'] or current['user_id'] != device['user_id'] or not transport.auth_valid(current['auth_hash'], current['user_id']):
                    continue
                transport.sender(json.loads(current['subscription']), dict(kind='family_activity',
                    title='家庭活动已结束', body='点击查看结果。', url='/home?panel=board&activity=' + identifier, tag=event_id))
                state = 'sent'
            except Exception as exc:
                expired = getattr(getattr(exc, 'response', None), 'status_code', None) in (404, 410)
                state = 'failed' if expired else 'pending'
                if expired:
                    with transport.store.db() as db:
                        db.execute('UPDATE chat_devices SET enabled=0 WHERE id=?', (device['id'],))
            with service.store.transaction() as doc:
                event = next((e for e in doc['notifications'].values() if e['id'] == event_id), None)
                if not event:
                    continue
                delivery = event.get('deliveries', {}).get(device['id'])
                if delivery and delivery.get('token') == token:
                    delivery.update(state='failed' if state != 'sent' and delivery['attempts'] >= 5 else state,
                                    next_at=now + min(300, 10 * 2 ** delivery['attempts']))
