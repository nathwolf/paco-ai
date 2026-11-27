"""Routine mailbox actions that should not become automatic commitments.

This applies to inferred email work only. Explicitly created or accepted tasks
remain under the user's control, even when they are small.
"""
import re
import unicodedata


def routine_account_action(title):
    text=' '.join(''.join(c for c in unicodedata.normalize('NFKD',title).casefold()
                          if not unicodedata.combining(c)).split())
    text=re.sub(r'^(please|por favor|veuillez)\s+','',text)
    verify=r'(verify|confirm|validate|verificar|verifica|confirmar|confirma|validar|valida|verifier|confirmer|valider)'
    email=r'(your |the |tu |su |el |la |votre |ton |l[’\x27])?(email(?: address)?|e-mail|correo(?: electronico)?|adresse (?:e-?mail|electronique)|courriel)\b'
    activate=r'(activate|activar|activa|activer)\s+.{0,40}\b(account|cuenta|compte|registration|signup|inscription)\b'
    login=r'(sign in|log in|iniciar sesion|inicia sesion|connectez-vous|se connecter)\b'
    return bool(re.match(verify+r'\s+'+email,text) or re.match(activate,text) or re.match(login,text))
