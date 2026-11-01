var $duration = 1000;
$(document).ready(function(){
	// - ACCOUNT DROPDOWN
	$('.ui.admindropdown').dropdown({
		transition: 'drop',
		on : 'click',
		duration  : 500		
	});
	$('.ui.moredropdown').dropdown({
		transition: 'fade down',
		duration  :300
	});

	// - SHOW & HIDE SIDEBAR
    $("#showmobiletabletsidebar").click(function(){
        $('.mobiletabletsidebar.animate .menu').transition({
		  	animation : 'swing right',
		    duration  : $duration
		  })
		;
		$('#mobiletabletsidebar').removeClass('hidden');
    });
    $("#hidemobiletabletsidebar").click(function(){
        $('.mobiletabletsidebar.animate .menu')
		  .transition({
		  	animation : 'fade',
		    duration  : $duration
		  });
    });
    $(".ui.accordion").accordion({
		exclusive: false
	});
});

//////// data table
$(document).ready(function(){
	// - MESSAGES
	$('.message .close').on('click', function() {
		$(this).closest('.message').transition('fade');
	});
	// - DATATABLES
//	$(document).ready(function(){
//		$('#example').DataTable();
//	});
//	var table = $('#example').DataTable({
//		lengthChange: false,
//		buttons: [ 'colvis']
//	});
//	table.buttons().container().appendTo(
//		$('div.eight.column:eq(0)', table.table().container())
//	);
});


  
 
 
