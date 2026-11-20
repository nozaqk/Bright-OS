import QtQuick 2.10
import QtQuick.Controls 2.3 as QtControls
import CalamaresSlideshow 1.0

/* Bright OS Calamares Slideshow - Installation Progress Slides */

Presentation {
    id: presentation
    height: 400
    width: 600

    // Slide 1: Welcome
    Slide {
        title: "Welcome to Bright OS"
        centeredText: true
        content: [
            text("Bright OS is an independent Linux desktop for developers,"),
            text("engineers, and technical professionals — built on Debian Linux"),
            text("with an original desktop environment called Bright Desktop."),
            text(""),
            text("This installer will set up Bright OS on your computer.")
        ]
    }

    // Slide 2: Three Editions
    Slide {
        title: "Three Editions, One Identity"
        centeredText: true
        content: [
            text("All editions share the same Bright visual identity:"),
            text(""),
            text("• Home — Friendly desktop for everyday users"),
            text("• Developer — Terminal, coding, and engineering tools"),
            text("• Lite — Lightweight profile for older hardware"),
            text(""),
            text("The installed edition is determined by the ISO you booted.")
        ]
    }

    // Slide 3: Bright Desktop
    Slide {
        title: "Bright Desktop"
        centeredText: true
        content: [
            text("A clean, modern desktop built with Qt 6 and QML:"),
            text(""),
            text("• Panel with clock and system tray"),
            text("• Dock with your favorite applications"),
            text("• Full-screen application launcher"),
            text("• Dark and light themes"),
            text("• Notification center and power controls")
        ]
    }

    // Slide 4: Ready-to-use Applications
    Slide {
        title: "Ready-to-Use Applications"
        centeredText: true
        content: [
            text("Included applications depend on your edition:"),
            text(""),
            text("• Firefox web browser"),
            text("• Office suite (Home/Developer)"),
            text("• Media player and utilities"),
            text("• Terminal and file manager"),
            text("• Development tools (Developer edition)"),
            text("• Flathub for additional applications")
        ]
    }

    // Slide 5: Ready
    Slide {
        title: "Almost There"
        centeredText: true
        content: [
            text("Your system is being installed."),
            text(""),
            text("After installation, your computer will restart"),
            text("and you can log in to Bright OS."),
            text(""),
            text("Thank you for trying Bright OS!")
        ]
    }

    // Auto-advance slides during installation
    Timer {
        interval: 8000
        running: true
        repeat: true
        onTriggered: presentation.goToNext()
    }
}
