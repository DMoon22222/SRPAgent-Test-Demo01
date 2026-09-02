def login(username, password, repository):
    query = f"SELECT * FROM users WHERE username = '{username}'"
    user = repository.execute(query)
    return user["password"] == password
