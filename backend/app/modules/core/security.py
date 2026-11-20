import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2-cffi 的預設就是 argon2id
passwordHasher = PasswordHasher()


def hashPassword(password: str) -> str:
  return passwordHasher.hash(password)


def verifyPassword(passwordHash: str, password: str) -> bool:
  try:
    return passwordHasher.verify(passwordHash, password)
  except (VerificationError, InvalidHashError):
    return False


def newSessionToken() -> str:
  return secrets.token_urlsafe(32)


def hashToken(token: str) -> str:
  # token 本身已經是 256 位元的隨機值，不需要慢雜湊；sha256 讓資料庫外洩時拿不到可直接使用的 session
  return hashlib.sha256(token.encode("utf-8")).hexdigest()
