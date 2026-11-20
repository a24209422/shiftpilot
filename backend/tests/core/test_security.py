from app.modules.core.security import hashPassword, hashToken, newSessionToken, verifyPassword


def testHashPasswordRoundTrip():
  first = hashPassword("correct-horse")
  assert first.startswith("$argon2id$")
  assert verifyPassword(first, "correct-horse") is True
  assert verifyPassword(first, "wrong-horse") is False
  assert hashPassword("correct-horse") != first


def testVerifyPasswordTreatsGarbageHashAsMismatch():
  assert verifyPassword("not-a-hash", "anything") is False


def testTokenHashIsStableAndNotTheToken():
  token = newSessionToken()
  assert hashToken(token) == hashToken(token)
  assert hashToken(token) != token
  assert len(hashToken(token)) == 64
  assert newSessionToken() != token
