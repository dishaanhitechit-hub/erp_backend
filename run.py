from app import create_app

app = create_app()
print("app create")

if __name__ == "__main__":
    app.run(debug=False)