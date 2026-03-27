
/*
var server = null;
if(window.location.protocol === 'http:')
	server = "http://" + window.location.hostname + ":8088/janus";
else
	server = "https://" + window.location.hostname + ":8089/janus";
*/
var janus = null;
var streaming = null;
var opaqueId = "streamingtest-"+Janus.randomString(12);

var bitrateTimer = null;






$(document).ready(function() {
	Janus.init({
		debug: "all", 
		callback: function() {
			if(!Janus.isWebrtcSupported()) {
				console.log("No WebRTC support... ");
				return;
			}
				// Create session
			janus = new Janus(
				{
					server: server,
					success: function() {
						// Attach to Streaming plugin
						janus.attach(
							{
								plugin: "janus.plugin.streaming",
								opaqueId: opaqueId,
								success: function(pluginHandle) {
									streaming = pluginHandle;
									Janus.log("Plugin attached! (" + streaming.getPlugin() + ", id=" + streaming.getId() + ")");
									// Setup streaming session
									startStream()
								
								},
								error: function(error) {
									Janus.error("  -- Error attaching plugin... ", error);
									console.log("Error attaching plugin... " + error);
								},
								iceState: function(state) {
									Janus.log("ICE state changed to " + state);
								},
								webrtcState: function(on) {
									Janus.log("Janus says our WebRTC PeerConnection is " + (on ? "up" : "down") + " now");
								},
								onmessage: function(msg, jsep) {
									Janus.debug(" ::: Got a message :::", msg);
									var result = msg["result"];
									if(result) {
										if(result["status"]) {
											var status = result["status"];
											if(status === 'starting')
												$('#status').text("Starting, please wait...").show();
											else if(status === 'started')
												$('#status').text("Started").show();
											else if(status === 'stopped')
												stopStream();
										} else 
											if(msg["streaming"] === "event") {
												// Is VP9/SVC in place?
												var spatial = result["spatial_layer"];
												temporal = result["temporal_layer"];
												if((spatial !== null && spatial !== undefined) || (temporal !== null && temporal !== undefined)) {
													if(!svcStarted) {
														svcStarted = true;
														addSvcButtons();
													}
													// We just received notice that there's been a switch, update the buttons
													updateSvcButtons(spatial, temporal);
												}
											}
									} else 
										if(msg["error"]) {
											console.log(msg["error"]);
											stopStream();
											return;
										}
									if(jsep) {
										Janus.debug("Handling SDP as well...", jsep);
										var stereo = (jsep.sdp.indexOf("stereo=1") !== -1);
										// Offer from the plugin, let's answer
										streaming.createAnswer(
											{
												jsep: jsep,
												// We want recvonly audio/video and, if negotiated, datachannels
												media: { audioSend: false, videoSend: false, data: true },
												customizeSdp: function(jsep) {
													if(stereo && jsep.sdp.indexOf("stereo=1") == -1) {
														// Make sure that our offer contains stereo too
														jsep.sdp = jsep.sdp.replace("useinbandfec=1", "useinbandfec=1;stereo=1");
													}
												},
												success: function(jsep) {
													Janus.debug("Got SDP!", jsep);
													var body = { request: "start" };
													streaming.send({ message: body, jsep: jsep });
												},
												error: function(error) {
													Janus.error("WebRTC error:", error);
													console.log("WebRTC error... " + error.message);
												}
											});
									}
								},
								onremotestream: function(stream) {
									Janus.debug(" ::: Got a remote stream :::", stream);
									if($('#remotevideo').length === 0) {
										addButtons = true;
										$('#stream').append('<video class="rounded centered hide" id="remotevideo" width="100%" height="100%" playsinline/>');
										$('#remotevideo').get(0).volume = 0;
										// Show the stream
										$("#remotevideo").bind("playing", function () {
											$('#waitingvideo').remove();
											if(this.videoWidth)
												$('#remotevideo').show();
											
											var videoTracks = stream.getVideoTracks();
											if(!videoTracks || videoTracks.length === 0)
												return;
											var width = this.videoWidth;
											var height = this.videoHeight;
											if(Janus.webRTCAdapter.browserDetails.browser === "firefox") {
												// Firefox Stable has a bug: width and height are not immediately available after a playing
												setTimeout(function() {
													var width = $("#remotevideo").get(0).videoWidth;
													var height = $("#remotevideo").get(0).videoHeight;
												}, 2000);
											}
										});
									}
									Janus.attachMediaStream($('#remotevideo').get(0), stream);
									//$("#btnStart").attr("disabled", false);
									var playPromise = $("#remotevideo").get(0).play();
									if (playPromise !== undefined) {
										playPromise.then(_ => {
										// Automatic playback started!
										// Show playing UI.
										})
										.catch(error => {
										// Auto-play was prevented
										// Show paused UI.
										});
									}


									$("#remotevideo").get(0).volume = 0;
									var videoTracks = stream.getVideoTracks();
									if(!videoTracks || videoTracks.length === 0) {
										// No remote video
										$('#remotevideo');
										if($('#stream .no-video-container').length === 0) {
											$('#stream').append(
												'<div class="no-video-container">' +
													'<i class="fa fa-video-camera fa-5 no-video-icon"></i>' +
													'<span class="no-video-text">No remote video available</span>' +
												'</div>');
										}
									} else {
										$('#stream .no-video-container').remove();
										$('#remotevideo').show();
									}

								},
								ondataopen: function(data) {
									Janus.log("The DataChannel is available!");
									$('#waitingvideo').remove();
									$('#stream').append(
										'<input class="form-control" type="text" id="datarecv" disabled></input>'
									);

								},
								ondata: function(data) {
									Janus.debug("We got data from the DataChannel!", data);
									$('#datarecv').val(data);
								},
								oncleanup: function() {
									Janus.log(" ::: Got a cleanup notification :::");
									$('#waitingvideo').remove();
									$('#remotevideo').remove();
									$('#datarecv').remove();
									$('.no-video-container').remove();
									$('#bitrate').attr('disabled', true);
									$('#bitrateset').html('Bandwidth<span class="caret"></span>');

									if(bitrateTimer)
										clearInterval(bitrateTimer);
									bitrateTimer = null;




								}
							});
					},
					error: function(error) {
						Janus.error(error);
						console.log(error, function() {
							window.location.reload();
						});
					},
					destroyed: function() {
						window.location.reload();
					}
			});
		}
	});
});

/*(document).destroy(
		function() {
			clearInterval(bitrateTimer);
			janus.destroy();
		}
	);
*/



function startStream() {

	Janus.log("Selected video id #" + selectedStream);


	var body = { request: "watch", id: parseInt(selectedStream) || selectedStream};
	streaming.send({ message: body });
	// No remote video yet
	$('#stream').append('<video class="rounded centered" id="waitingvideo" width="100%" height="100%" />');

	// Get some more info for the mountpoint to display, if any
}

function stopStream() {
	var body = { request: "stop" };
	streaming.send({ message: body });
	streaming.hangup();

	$('#status').empty();
	$('#bitrate').attr('disabled', true);
	$('#bitrateset').html('Bandwidth<span class="caret"></span>');
	
	if(bitrateTimer)
		clearInterval(bitrateTimer);
	bitrateTimer = null;
	$('#curres').empty();

}

