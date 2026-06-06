import uvicorn

if __name__ == "__main__":
    print("Starting ThalassemiaFree AI — BloodBridge 2.0 Backend...")
    print("URL: http://127.0.0.1:8000")
    print("API Documentation: http://127.0.0.1:8000/docs")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
