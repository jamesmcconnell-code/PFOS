from app.security import hash_password, verify_password, create_token, decode_token
def test_password_round_trip():
    hashed=hash_password('correct-horse-battery-staple')
    assert verify_password('correct-horse-battery-staple',hashed)
    assert not verify_password('wrong',hashed)
def test_jwt_round_trip(): assert decode_token(create_token('user-123'))=='user-123'
