import asyncio
import edge_tts

async def _generate():
    print("Generating Edge TTS...")
    communicate = edge_tts.Communicate("This is a fallback test.", "en-US-ChristopherNeural")
    await communicate.save("test_edge.mp3")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_generate())
        print("Done. Check test_edge.mp3")
    finally:
        loop.close()
