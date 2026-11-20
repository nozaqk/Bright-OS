import QtQuick 2.10
import QtQuick.Controls 2.3 as QtControls
import CalamaresSlideshow 1.0

/* Bright OS Calamares Slideshow */
Presentation {
    id: presentation
    height: 400
    width: 600
    
    // Slide 1: Welcome
    Slide {
        title: "Welcome to Bright OS"
        centeredText: true
        content: [
            text("Bright OS is an independent Linux desktop for developers, engineers, and technical professionals."),
            text(""),
            text("This installer will guide you through setting up Bright OS on your computer.")
        ]
    }
    
    // Slide 2: Desktop
    Slide {
        title: "Bright Desktop"
        centeredText: true
        content: [
            text("A clean, modern desktop environment built with Qt and QML."),
            text(""),
            text("• Top panel with clock and system tray"),
            text("• Dock with your favorite applications"),
            text("• Full-screen launcher"),
            text("• Dark and light themes"),
            text("• Smooth animations")
        ]
    }
    
    // Slide 3: Applications
    Slide {
        title: "Ready-to-use Applications"
        centeredText: true
        content: [
            text("Bright OS comes with everything you need:"),
            text(""),
            text("• Firefox web browser"),
            text("• LibreOffice suite"),
            text("• VLC media player"),
            text("• Terminal, file manager, and system tools"),
            text("• Optional developer & electronics toolchains")
        ]
    }
    
    // Slide 4: Windows Compatibility
    Slide {
        title: "Windows Compatibility"
        centeredText: true
        content: [
            text("Run Windows applications with Wine."),
            text(""),
            text("Install your favorite games and applications from the Windows ecosystem.")
        ]
    }
    
    // Slide 5: Ready
    Slide {
        title: "Enjoy Bright OS"
        centeredText: true
        content: [
            text("Your system will be ready shortly."),
            text(""),
            text("After installation, log in and explore Bright OS.")
        ]
    }
    
    // Timer to advance slides automatically
    Timer {
        interval: 8000
        running: true
        repeat: true
        onTriggered: presentation.goToNext()
    }
}
