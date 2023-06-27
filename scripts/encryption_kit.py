import bcrypt

def salt_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_pw.decode('utf-8')


def check_password(raw_password: str, hashed_pw: str) -> bool:
    return bcrypt.checkpw(raw_password.encode('utf-8'), hashed_pw.encode('utf-8'))


if __name__ == '__main__':
    password = input('Enter the password to salt: ')
    hashed_password = salt_password(password)
    print('Salted Password:', hashed_password)

    raw_password = input('Enter the raw password to check: ')
    is_match = check_password(raw_password, hashed_password)
    print('Password Match:', is_match)