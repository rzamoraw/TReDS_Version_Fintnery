from passlib.context import CryptContext

# Este objeto se usa para hashear y verificar contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")