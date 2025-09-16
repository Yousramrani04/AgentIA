import openai
# Exemple de stockage de l'historique
chat_history = []

def generate_plan(user_input):
    prompt = f"""
    Tu es un coach expert. Crée un plan détaillé et structuré pour :
    "{user_input}"

    🔹 Plan par jour avec exercices précis
    🔹 Conseils pratiques et astuces
    🔹 Explique pourquoi chaque exercice est utile
    🔹 Utilise des emojis
    """

    # Stocker uniquement le message de l'utilisateur dans l'historique
    chat_history.append({"role": "user", "content": user_input})

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=700
    )

    reply = response['choices'][0]['message']['content']
    return reply


# Exemple : affichage de l'historique uniquement côté "user"
def get_user_history():
    return [msg["content"] for msg in chat_history if msg["role"] == "user"]
