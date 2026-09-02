def update_email(user_id, email, repository):
    repository.execute(f"UPDATE users SET email = '{email}' WHERE id = {user_id}")
    return {"user_id": user_id, "email": email}
