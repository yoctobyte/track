# Detailed Transcription of User Feedback (2026-04-14)

This document contains a literal (cleaned of "ums" and "ahs") transcription of the 10-minute audio sequence provided by the user. It is intended to serve as a high-fidelity reference for architectural planning.

---

### Part 1: The Umbrella Vision and Sub-Projects
"What's up is that in Track, we are going to put multiple projects. So we have a project that inventories the network, right? We have a project to map 3D space. We have another project that just gives access to web control of certain devices. We have another project where we sort of go with Ansible to automate some tasks and configure it, right? 

And right now, the Map3D just takes the whole web interface as a single application, and that's not really what we intend, although the web interface itself is fine. Map3D is just one of these sub-applications. So we might sort of want to review that. We can totally keep what we have already and just extend that web page, that's fine. Just notice that the Map project itself is not the main project; it's just a sub-project."

### Part 2: Development, Workstations, and Server Transition
"Another problem that we are having in a way is that we are developing on our workstation. Like right today, I was at work and I wanted to make a session for the Map3D to collect some images, but I turned off my workstation at home and hence Cloudflare had no tunnel inside. So, well, that was silly of me. 

But it also reminds me that in the future, once we're sort of done developing or at least gone a long way, this will run on a server. And then we have the issue that this will run on a server without a GPU, however, we will run model updates for the Map3D etcetera and render stuff, and that we do on a node with a proper GPU. 

So I think the easiest way is that we would just mount a drive, right, and run our software from there locally with all the files, but then we get into this funky issue that if we mount it, then the VM will clash with whatever is running on the server, which may be an entirely different processor even. So that's a design consideration I didn't figure out yet how to deal with this."

### Part 3: Architecture and Unification
"It's also the fact that this has multiple sub-projects, but I still like to have them as one web interface that rules them all, even if the projects are independently developed, right? That's really something to keep in mind, to let's architect that right now properly instead of later as an afterthought."

### Part 4: Data Sharing and Master Tags
"And what those projects do have in common is they will share some data, at least like location. So the root location and other sub-locations and anything we tag, right? And those tags, but then the type of data we are storing is really very different because like our net inventory will collect data about the network, that just deserves its own database. 

The only thing we actually share are like tags, and we should be freely able to edit and import/export. So I suggest we have like a master tag record that the user can just use as a quick pull-down, like 'I'm here and there'. And at any application, it's free to edit any custom tags."

### Part 5: Multi-Location Security and Credentials
"Now speaking of that, locations. So I figured our web frontend, right now we log in once and then only then we select a location. I would really like to change that. So per location, we have a web and control software and a distinct password, right? 

So we have an environment 'Testing', that would just be my home, and I would be the only one to log in. The people at the museum have no need to watch my home, right? And then again, the museum itself would have an entry page, the location at work itself, right, and another location should also have its own page with its own credentials. Those can be simple and shared, right? 

But so the root page would be like, 'Okay, where did you want to go? Do you want to go to Testing, do you want to go to the museum, or do you want to go to the lab?' right? And once the user selects that, we ask for appropriate credentials for that space. And we just mirror functionality for pretty much any testing environment, but we are sorting it up as main location. And also notice that any location may again have a lot of sub-locations, pretty much as we do it now, right? And sub-sub-locations. So that's something to keep in mind, but I think splitting that off would be very helpful at the moment."

---
*End of transcription.*
