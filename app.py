from quart import Quart, render_template, websocket

app = Quart(__name__)

@app.route("/")
async def hello():
    return 'hello'

if __name__ == "__main__":
    app.run()