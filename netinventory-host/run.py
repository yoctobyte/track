from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["NETINV_HOST_BIND"],
        port=app.config["NETINV_HOST_PORT"],
        debug=False,
    )
